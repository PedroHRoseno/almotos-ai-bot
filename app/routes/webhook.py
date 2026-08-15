import hmac
import hashlib
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.models.whatsapp import WebhookPayload
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.chat_service import ChatService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp"])


def _get_chat_service() -> ChatService:
    settings = get_settings()
    return ChatService(
        settings=settings,
        whatsapp=WhatsAppService(settings),
        almotos_ai=AlmotosAiClient(settings),
    )


def _mask(value: str) -> str:
    if not value:
        return "<vazio>"
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}…{value[-2:]} (len={len(value)})"


def verify_meta_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header:
        return False
    received = header.strip()
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, received)


@router.get("/webhook")
async def verify_webhook(request: Request) -> Response:
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
    return PlainTextResponse(content=hub_challenge, status_code=200)


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    raw = await request.body()
    settings = get_settings()
    secret = (settings.whatsapp_app_secret or "").strip()
    signature = request.headers.get("x-hub-signature-256")

    if secret:
        if not verify_meta_signature(secret, raw, signature):
            logger.warning("Webhook POST rejeitado: assinatura X-Hub-Signature-256 inválida")
            return Response(status_code=403, content="Forbidden", media_type="text/plain")
    elif not settings.debug:
        logger.warning(
            "WHATSAPP_APP_SECRET ausente — recusando POST em produção. "
            "Defina o App Secret ou DEBUG=true só em local."
        )
        return Response(status_code=403, content="Forbidden", media_type="text/plain")

    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        logger.warning("Webhook POST com body inválido")
        return Response(status_code=200, content="OK", media_type="text/plain")

    try:
        payload = WebhookPayload.model_validate(body)
    except Exception:
        logger.warning("Webhook POST com payload não reconhecido")
        return Response(status_code=200, content="OK", media_type="text/plain")

    whatsapp = WhatsAppService(settings)
    messages = whatsapp.parse_incoming_messages(payload)

    if messages:
        chat = _get_chat_service()

        async def process_all() -> None:
            for msg in messages:
                await chat.handle_incoming_message(msg)

        background_tasks.add_task(process_all)
        logger.info("Webhook POST: %s mensagem(ns) enfileirada(s)", len(messages))

    return Response(status_code=200, content="OK", media_type="text/plain")
