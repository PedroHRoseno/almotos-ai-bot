import asyncio
import logging
import random
import re

from app.config import Settings
from app.models.chatwoot import ChatwootWebhookPayload
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.chatwoot_client import ChatwootClient
from app.services.evolution_client import EvolutionClient
from app.services.reply_guard import typing_seconds
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
_PRICE_QUESTION = re.compile(
    r"(qual\s+(?:e\s+|é\s+|o\s+)?pre[cç]o|"
    r"quanto\s+(?:custa|é|e|fica|sai)|"
    r"pre[cç]o\s+(?:dela|dele|disso|dessa|desse)|"
    r"(?:me\s+)?fala(?:r)?\s+o\s+pre[cç]o|"
    r"valor\s+(?:dela|dele|disso))",
    re.IGNORECASE,
)
_NEGOTIATION_PATTERN = re.compile(
    r"\b("
    r"desconto|parcela|financi|negoci|"
    r"entrada|à\s*vista|a\s*vista|"
    r"visitar|loja"
    r")\b",
    re.IGNORECASE,
)


class ChatwootChatService:
    """Cola webhook Chatwoot → orquestrador (`/v1/chat`) → Chatwoot.

    Texto e fotos saem como outgoing na caixa (a caixa entrega no WhatsApp).
    Fotos: multipart `attachments[]` com a URL pública do catálogo. Evolution
    só entra como fallback de mídia e para presença/leitura.
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
            await asyncio.sleep(random.uniform(1.1, 3.0))
            if number and self._evolution.configured():
                await self._evolution.signal_reading(number, payload.whatsapp_message_id())

            result = await self._almotos_ai.complete(thread_id=thread_id, text=user_text)
            text, extracted = format_whatsapp_reply(result.get("text") or "")
            images = unique_media_urls((result.get("images") or []) + extracted)
            handoff = self._should_handoff(user_text, bool(result.get("handoff")))

            text_sent, photos_sent = await self._deliver(
                conversation_id, number, text, images
            )
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

    async def _deliver(
        self,
        conversation_id: int,
        number: str | None,
        text: str,
        images: list[str],
    ) -> tuple[bool, int]:
        photos = unique_media_urls(images)
        if not photos:
            if not text:
                return False, 0
            extra = typing_seconds(text)
            if number and self._evolution.configured():
                await self._evolution.send_presence(number, delay_ms=int(extra * 1000))
            sent = await self._chatwoot.send_message(
                conversation_id,
                text,
                whatsapp_number=number,
                extra_seconds=extra,
            )
            return sent, 0

        text_sent = False
        photos_sent = 0
        for index, image_url in enumerate(photos):
            caption = text if index == 0 else ""
            extra = typing_seconds(caption, kind="media")
            if number and self._evolution.configured():
                await self._evolution.send_presence(number, delay_ms=int(extra * 1000))
            ok = await self._chatwoot.send_attachment(
                conversation_id,
                image_url,
                caption=caption,
                whatsapp_number=number,
                extra_seconds=extra,
            )
            if not ok:
                if caption and not text_sent:
                    text_sent = await self._chatwoot.send_message(
                        conversation_id,
                        caption,
                        whatsapp_number=number,
                    )
                if number and self._evolution.configured():
                    logger.warning(
                        "Chatwoot attachment falhou, tentando Evolution sendMedia conversation=%s",
                        conversation_id,
                    )
                    ok = await self._evolution.send_media(number, image_url, caption=caption)
                else:
                    logger.warning(
                        "Foto não enviada: Chatwoot attachment falhou e Evolution indisponível "
                        "(conversation=%s url=%s)",
                        conversation_id,
                        image_url[:180],
                    )
            elif caption:
                text_sent = True
            if ok:
                photos_sent += 1
        return text_sent, photos_sent

    def _should_handoff(self, user_text: str, model_handoff: bool) -> bool:
        if self._wants_human(user_text):
            return True
        if model_handoff and self._is_listed_price_question(user_text):
            logger.info(
                "Handoff ignorado: cliente só perguntou o preço cadastrado"
            )
            return False
        return model_handoff

    @staticmethod
    def _wants_human(text: str) -> bool:
        return bool(_HANDOFF_PATTERN.search(text or ""))

    @staticmethod
    def _is_listed_price_question(text: str) -> bool:
        raw = text or ""
        if not _PRICE_QUESTION.search(raw):
            return False
        return not _NEGOTIATION_PATTERN.search(raw) and not _HANDOFF_PATTERN.search(raw)
