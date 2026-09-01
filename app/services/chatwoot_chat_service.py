import logging
import re

from app.config import Settings
from app.models.chatwoot import ChatwootWebhookPayload
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.chatwoot_client import ChatwootClient
from app.services.evolution_client import EvolutionClient
from app.services.whatsapp_format import format_whatsapp_reply, unique_media_urls

logger = logging.getLogger(__name__)

_FALLBACK_REPLY = (
    "Desculpe, tivemos um problema técnico. "
    "Tente novamente em alguns minutos ou entre em contato com nossa loja."
)

_HANDOFF_PATTERN = re.compile(
    r"\b("
    r"atendente|humano|vendedor|"
    r"pessoa\s+real|"
    r"falar\s+com\s+(algu[eé]m|voc[eê]s)|"
    r"fechar\s+(neg[oó]cio|a\s+compra)"
    r")\b",
    re.IGNORECASE,
)


class ChatwootChatService:
    """Cola webhook Chatwoot → orquestrador (`/v1/chat`) → Chatwoot (+ fotos Evolution).

    Texto sai como outgoing no Chatwoot (a caixa entrega no WhatsApp). Não usamos
    Evolution sendText neste caminho — isso ecoava no webhook e gerava loop.
    Fotos: `/message/sendMedia`, só URLs distintas do cadastro.
    """

    def __init__(
        self,
        settings: Settings,
        chatwoot: ChatwootClient,
        almotos_ai: AlmotosAiClient,
        evolution: EvolutionClient | None = None,
    ) -> None:
        self._settings = settings
        self._chatwoot = chatwoot
        self._almotos_ai = almotos_ai
        self._evolution = evolution or EvolutionClient(settings)

    async def handle_incoming(self, payload: ChatwootWebhookPayload) -> None:
        if payload.conversation is None:
            return
        if payload.is_with_human():
            logger.info(
                "Chatwoot conversa %s já com humano (status=%s) — bot silencia",
                payload.conversation.id,
                payload.conversation.status,
            )
            return

        conversation_id = payload.conversation.id
        user_text = (payload.content or "").strip()
        sender_name = (payload.sender.name if payload.sender else None) or "contato"
        number = payload.whatsapp_number()
        thread_id = f"chatwoot:{conversation_id}"

        logger.info(
            "Chatwoot incoming conversation=%s sender=%s status=%s",
            conversation_id,
            sender_name,
            payload.conversation.status,
        )

        try:
            result = await self._almotos_ai.complete(thread_id=thread_id, text=user_text)
            text, extracted = format_whatsapp_reply(result.get("text") or "")
            images = unique_media_urls((result.get("images") or []) + extracted)
            handoff = bool(result.get("handoff")) or self._wants_human(user_text)

            text_sent = False
            if text:
                text_sent = await self._chatwoot.send_message(
                    conversation_id, text, whatsapp_number=number
                )

            photos_sent = await self._send_photos(payload, images)
            if not text_sent and not photos_sent:
                logger.error("Resposta gerada mas não enviada na conversa %s", conversation_id)
                await self._chatwoot.send_message(
                    conversation_id, _FALLBACK_REPLY, whatsapp_number=number
                )

            if handoff:
                await self._chatwoot.handoff_to_human(conversation_id)
                await self._chatwoot.send_private_note(
                    conversation_id,
                    "Handoff: o bot passou o atendimento para um humano nesta mesma conversa.",
                )
        except Exception:
            logger.exception("Erro ao processar conversa Chatwoot %s", conversation_id)
            await self._chatwoot.send_message(
                conversation_id, _FALLBACK_REPLY, whatsapp_number=number
            )

    async def _send_photos(self, payload: ChatwootWebhookPayload, images: list[str]) -> int:
        photos = unique_media_urls(images)
        if not photos:
            return 0
        number = payload.whatsapp_number()
        if not number:
            logger.warning(
                "Fotos ignoradas: remoteJid/telefone ausente na conversa %s",
                payload.conversation.id if payload.conversation else "?",
            )
            return 0
        if not self._evolution.configured():
            logger.warning(
                "Fotos ignoradas: Evolution API não configurada (conversation=%s)",
                payload.conversation.id if payload.conversation else "?",
            )
            return 0

        sent = 0
        for image_url in photos:
            if await self._evolution.send_media(number, image_url):
                sent += 1
        return sent

    @staticmethod
    def _wants_human(text: str) -> bool:
        return bool(_HANDOFF_PATTERN.search(text or ""))
