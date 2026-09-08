import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.config import get_settings
from app.models.chatwoot import ChatwootWebhookPayload
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.chatwoot_chat_service import ChatwootChatService
from app.services.chatwoot_client import ChatwootClient
from app.services.message_buffer import get_message_buffer
from app.services.reply_guard import contact_key, get_reply_guard, shared_fingerprints

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chatwoot"])


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

    if payload.attachments and not (payload.content or "").strip():
        logger.info(
            "Chatwoot evento de mídia sem legenda conversation=%s — IA não processa",
            payload.conversation.id if payload.conversation else "?",
        )
        return Response(status_code=200, content="OK", media_type="text/plain")

    if not payload.should_process_ai():
        logger.info(
            "Chatwoot ignorado event=%s type=%s sender=%s status=%s",
            payload.event,
            payload.message_type,
            (payload.sender.type if payload.sender else None),
            payload.conversation.status if payload.conversation else None,
        )
        return Response(status_code=200, content="OK", media_type="text/plain")

    number = payload.whatsapp_number()
    conv_id = payload.conversation.id if payload.conversation else None
    if conv_id is None:
        return Response(status_code=200, content="OK", media_type="text/plain")

    key = contact_key(number) or f"cw:{conv_id}"
    fps = shared_fingerprints(
        contact_key=key,
        text=payload.content or "",
        source_id=f"cw:{payload.id}" if payload.id is not None else None,
    )
    claimed = await get_reply_guard().claim_inbound(
        contact_key=key,
        fingerprints=fps,
        text=payload.content or "",
    )
    if not claimed:
        return Response(status_code=200, content="OK", media_type="text/plain")

    generation = await get_message_buffer().push(conv_id, payload.content or "", payload)
    chat = _get_chatwoot_chat_service()
    background_tasks.add_task(chat.flush_after_debounce, conv_id, generation)
    logger.info(
        "Webhook Chatwoot: conversa %s no buffer gen=%s (debounce %.0fs)",
        conv_id,
        generation,
        get_settings().chatwoot_debounce_seconds,
    )
    return Response(status_code=200, content="OK", media_type="text/plain")
