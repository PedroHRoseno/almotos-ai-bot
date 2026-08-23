import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.config import get_settings
from app.models.chatwoot import ChatwootWebhookPayload
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.chatwoot_chat_service import ChatwootChatService
from app.services.chatwoot_client import ChatwootClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chatwoot"])

# Pausa no worker (não no request) para o WhatsApp/Evolution não marcar a sessão como bot.
_HUMAN_TYPING_DELAY_SECONDS = 4


def _get_chatwoot_chat_service() -> ChatwootChatService:
    settings = get_settings()
    return ChatwootChatService(
        settings=settings,
        chatwoot=ChatwootClient(settings),
        almotos_ai=AlmotosAiClient(settings),
    )


@router.post("/webhook/chatwoot")
async def receive_chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """Webhook AgentBot. Sempre 200 para o Chatwoot não retentar em loop."""
    raw = await request.body()
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
        payload = ChatwootWebhookPayload.model_validate(body)
    except Exception:
        logger.warning("Webhook Chatwoot com payload inválido")
        return Response(status_code=200, content="OK", media_type="text/plain")

    # Regra de ouro: outgoing / evento ≠ message_created → ack e sai (anti-loop).
    if payload.event != "message_created" or payload.is_outgoing:
        logger.debug(
            "Chatwoot ignorado event=%s message_type=%s",
            payload.event,
            payload.message_type,
        )
        return Response(status_code=200, content="OK", media_type="text/plain")

    if not payload.should_process_ai():
        return Response(status_code=200, content="OK", media_type="text/plain")

    chat = _get_chatwoot_chat_service()

    async def process_incoming() -> None:
        # FastAPI já devolveu 200; sleep aqui não segura o webhook nem a thread.
        await asyncio.sleep(_HUMAN_TYPING_DELAY_SECONDS)
        await chat.handle_incoming(payload)

    background_tasks.add_task(process_incoming)
    logger.info(
        "Webhook Chatwoot: conversa %s enfileirada (pausa humana %ss no worker)",
        payload.conversation.id if payload.conversation else "?",
        _HUMAN_TYPING_DELAY_SECONDS,
    )
    return Response(status_code=200, content="OK", media_type="text/plain")
