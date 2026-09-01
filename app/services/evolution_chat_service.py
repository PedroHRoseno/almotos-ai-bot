import logging

from app.config import Settings
from app.models.evolution import EvolutionIncomingMessage
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.evolution_client import EvolutionClient
from app.services.whatsapp_format import format_whatsapp_reply, merge_image_urls

logger = logging.getLogger(__name__)

_FALLBACK_REPLY = (
    "Desculpe, tivemos um problema técnico. "
    "Tente novamente em alguns minutos ou entre em contato com nossa loja."
)
_MEDIA_WITHOUT_CAPTION = (
    "Recebi sua mídia. Pode descrever o que você procura? "
    "Por exemplo: modelo, ano ou faixa de preço."
)


class EvolutionChatService:
    """Cola webhook Evolution → orquestrador (`/v1/chat`) → Evolution API.

    Texto sai em `/message/sendText`; fotos do estoque em `/message/sendMedia`.
    A lógica de LLM permanece no `almotos-ai` (ADR-003).
    """

    def __init__(
        self,
        settings: Settings,
        evolution: EvolutionClient,
        almotos_ai: AlmotosAiClient,
    ) -> None:
        self._settings = settings
        self._evolution = evolution
        self._almotos_ai = almotos_ai

    async def handle_incoming(self, message: EvolutionIncomingMessage) -> None:
        if message.from_me:
            return

        user_text = (message.text or "").strip()
        if message.kind == "media" and not user_text:
            logger.info(
                "Evolution mídia sem legenda remoteJid=%s media_type=%s — sem chamada à IA",
                message.remote_jid,
                message.media_type,
            )
            await self._evolution.send_text(message.number, _MEDIA_WITHOUT_CAPTION)
            return

        if not user_text:
            logger.info("Evolution evento sem texto remoteJid=%s — ignorado", message.remote_jid)
            return

        thread_id = f"wa:{message.number}"
        try:
            result = await self._almotos_ai.complete(thread_id=thread_id, text=user_text)
            text, extracted = format_whatsapp_reply(result.get("text") or "")
            images = merge_image_urls(result.get("images") or [], extracted)
            await self._deliver(message.number, text, images)
        except Exception:
            logger.exception("Erro ao processar Evolution remoteJid=%s", message.remote_jid)
            await self._evolution.send_text(message.number, _FALLBACK_REPLY)

    async def _deliver(self, number: str, text: str, images: list[str]) -> None:
        text_sent = False
        if text:
            text_sent = await self._evolution.send_text(number, text)

        photos_sent = 0
        for index, image_url in enumerate(images):
            caption = text if index == 0 and not text_sent else ""
            if await self._evolution.send_media(number, image_url, caption=caption):
                photos_sent += 1

        if not text_sent and not photos_sent:
            logger.error("Resposta gerada mas não enviada para %s", number)
