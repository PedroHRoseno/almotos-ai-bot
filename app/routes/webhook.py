import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import PlainTextResponse

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


def _mask(value: str) -> str:
    if not value:
        return "<vazio>"
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}…{value[-2:]} (len={len(value)})"


@router.get("/webhook")
async def verify_webhook(request: Request) -> Response:
    """
    Verificação inicial do webhook da Meta (WhatsApp Cloud API).

    A Meta envia GET com query params hub.mode, hub.verify_token e hub.challenge.
    Em sucesso, retorna APENAS hub.challenge em text/plain (sem JSON).
    """
    params = request.query_params
    hub_mode = params.get("hub.mode", "")
    hub_verify_token = params.get("hub.verify_token", "")
    hub_challenge = params.get("hub.challenge", "")

    settings = get_settings()
    expected_token = (settings.whatsapp_verify_token or "").strip()

    logger.info(
        "Webhook GET verificação Meta | hub.mode=%r | hub.verify_token=%s | "
        "hub.challenge_len=%s | expected_token_configured=%s expected_token_len=%s",
        hub_mode,
        _mask(hub_verify_token.strip()),
        len(hub_challenge),
        bool(expected_token),
        len(expected_token),
    )

    if hub_mode != "subscribe":
        logger.warning("Webhook rejeitado: hub.mode=%r (esperado 'subscribe')", hub_mode)
        return Response(status_code=403, content="Forbidden", media_type="text/plain")

    if not hub_verify_token.strip() or not expected_token:
        logger.warning(
            "Webhook rejeitado: token ausente (recebido=%s configurado=%s)",
            bool(hub_verify_token.strip()),
            bool(expected_token),
        )
        return Response(status_code=403, content="Forbidden", media_type="text/plain")

    if hub_verify_token.strip() != expected_token:
        logger.warning(
            "Webhook rejeitado: hub.verify_token não confere com WHATSAPP_VERIFY_TOKEN"
        )
        return Response(status_code=403, content="Forbidden", media_type="text/plain")

    if not hub_challenge:
        logger.warning("Webhook rejeitado: hub.challenge ausente")
        return Response(status_code=403, content="Forbidden", media_type="text/plain")

    logger.info("Webhook verificado com sucesso; retornando hub.challenge")
    # Meta exige corpo = apenas o valor de hub.challenge (text/plain), status 200
    return PlainTextResponse(content=hub_challenge, status_code=200)


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Recebe eventos da Meta. Responde 200 imediatamente; processa mensagens em background.
    """
    try:
        body = await request.json()
    except Exception:
        logger.warning("Webhook POST com body inválido")
        return Response(status_code=200, content="OK", media_type="text/plain")

    try:
        payload = WebhookPayload.model_validate(body)
    except Exception:
        logger.warning("Webhook POST com payload não reconhecido")
        return Response(status_code=200, content="OK", media_type="text/plain")

    whatsapp = WhatsAppService(get_settings())
    messages = whatsapp.parse_incoming_messages(payload)

    if messages:
        chat = _get_chat_service()

        async def process_all() -> None:
            for msg in messages:
                await chat.handle_incoming_message(msg)

        background_tasks.add_task(process_all)
        logger.info("Webhook POST: %s mensagem(ns) enfileirada(s)", len(messages))

    return Response(status_code=200, content="OK", media_type="text/plain")
