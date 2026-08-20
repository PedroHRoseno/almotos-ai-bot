import logging
import re

from app.config import Settings
from app.models.chatwoot import ChatwootWebhookPayload
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.chatwoot_client import ChatwootClient

logger = logging.getLogger(__name__)

_FALLBACK_REPLY = (
    "Desculpe, tivemos um problema técnico. "
    "Tente novamente em alguns minutos ou entre em contato com nossa loja."
)

_HANDOFF_PATTERN = re.compile(
    r"\b(atendente|humano|vendedor|pessoa\s+real|falar\s+com\s+(algu[eé]m|voc[eê]s))\b",
    re.IGNORECASE,
)


class ChatwootChatService:
    """Cola webhook Chatwoot → orquestrador (`/v1/chat`) → API Chatwoot.

    A lógica de LLM permanece no `almotos-ai` (ADR-003). Este serviço só
    extrai o texto de entrada e devolve a resposta na conversa.
    """

    def __init__(
        self,
        settings: Settings,
        chatwoot: ChatwootClient,
        almotos_ai: AlmotosAiClient,
    ) -> None:
        self._settings = settings
        self._chatwoot = chatwoot
        self._almotos_ai = almotos_ai

    async def handle_incoming(self, payload: ChatwootWebhookPayload) -> None:
        if payload.conversation is None:
            return
        conversation_id = payload.conversation.id
        user_text = (payload.content or "").strip()
        sender_name = (payload.sender.name if payload.sender else None) or "contato"
        thread_id = f"chatwoot:{conversation_id}"

        logger.info(
            "Chatwoot incoming conversation=%s sender=%s status=%s",
            conversation_id,
            sender_name,
            payload.conversation.status,
        )

        try:
            reply = await self._ask_llm(thread_id=thread_id, text=user_text)
            sent = await self._chatwoot.send_message(conversation_id, reply)
            if not sent:
                logger.error("Resposta gerada mas não enviada na conversa %s", conversation_id)

            if self._wants_human(user_text):
                await self._chatwoot.handoff_to_human(conversation_id)
        except Exception:
            logger.exception("Erro ao processar conversa Chatwoot %s", conversation_id)
            await self._chatwoot.send_message(conversation_id, _FALLBACK_REPLY)

    async def _ask_llm(self, *, thread_id: str, text: str) -> str:
        """Ponto de encaixe da IA: só encaminha para o orquestrador."""
        result = await self._almotos_ai.complete(thread_id=thread_id, text=text)
        return (result.get("text") or "").strip() or _FALLBACK_REPLY

    @staticmethod
    def _wants_human(text: str) -> bool:
        return bool(_HANDOFF_PATTERN.search(text or ""))
