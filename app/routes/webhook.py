import logging

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from app.config import get_settings
from app.models.whatsapp import WebhookPayload
from app.services.chat_service import ChatService
from app.services.openai_service import OpenAIService
from app.services.vehicles_api import VehiclesApiService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp"])


def _get_chat_service() -> ChatService:
    settings = get_settings()
    return ChatService(
        settings=settings,
        whatsapp=WhatsAppService(settings),
        vehicles_api=VehiclesApiService(settings),
        openai=OpenAIService(settings),
    )


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> Response:
    """
    Verificação inicial do webhook da Meta (WhatsApp Cloud API).
    Retorna hub.challenge quando o verify token confere.
    """
    settings = get_settings()
    whatsapp = WhatsAppService(settings)
    challenge = whatsapp.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        return Response(status_code=403, content="Forbidden")
    return Response(content=challenge, media_type="text/plain")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """
    Recebe eventos da Meta. Responde 200 imediatamente e processa mensagens em background.
    """
    try:
        body = await request.json()
    except Exception:
        logger.warning("Webhook recebido com body inválido")
        return {"status": "ignored"}

    payload = WebhookPayload.model_validate(body)
    whatsapp = WhatsAppService(get_settings())
    messages = whatsapp.parse_incoming_messages(payload)

    if not messages:
        return {"status": "ok"}

    chat = _get_chat_service()

    async def process_all() -> None:
        for msg in messages:
            await chat.handle_incoming_message(msg)

    # Meta exige resposta rápida; processamento assíncrono após o 200
    background_tasks.add_task(process_all)

    return {"status": "ok"}
