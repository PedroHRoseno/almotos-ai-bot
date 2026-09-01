import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.config import Settings, get_settings
from app.models.evolution import EvolutionWebhookPayload, parse_evolution_payload
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.evolution_chat_service import EvolutionChatService
from app.services.evolution_client import EvolutionClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evolution"])

_HUMAN_TYPING_DELAY_SECONDS = 4


def _get_evolution_chat_service() -> EvolutionChatService:
    settings = get_settings()
    return EvolutionChatService(
        settings=settings,
        evolution=EvolutionClient(settings),
        almotos_ai=AlmotosAiClient(settings),
    )


def _apikey_ok(settings: Settings, payload: EvolutionWebhookPayload, header_key: str | None) -> bool:
    expected = (settings.evolution_api_key or "").strip()
    if not expected:
        return True
    received = (payload.apikey or header_key or "").strip()
    return bool(received) and received == expected


@router.post("/webhook/evolution")
async def receive_evolution_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """Webhook Evolution API. Sempre 200 para a Evolution não retentar em loop."""
    raw = await request.body()
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
        payload = EvolutionWebhookPayload.model_validate(body)
    except Exception:
        logger.warning("Webhook Evolution com payload inválido")
        return Response(status_code=200, content="OK", media_type="text/plain")

    settings = get_settings()
    header_key = request.headers.get("apikey") or request.headers.get("x-api-key")
    if not _apikey_ok(settings, payload, header_key):
        logger.warning("Webhook Evolution rejeitado: apikey inválida")
        return Response(status_code=401, content="Unauthorized", media_type="text/plain")

    if not payload.is_upsert():
        logger.debug("Evolution ignorado event=%s", payload.event)
        return Response(status_code=200, content="OK", media_type="text/plain")

    messages = parse_evolution_payload(body)
    if not messages:
        return Response(status_code=200, content="OK", media_type="text/plain")

    chat = _get_evolution_chat_service()

    async def process_incoming() -> None:
        await asyncio.sleep(_HUMAN_TYPING_DELAY_SECONDS)
        for msg in messages:
            await chat.handle_incoming(msg)

    background_tasks.add_task(process_incoming)
    logger.info(
        "Webhook Evolution: %s mensagem(ns) enfileirada(s) (pausa humana %ss)",
        len(messages),
        _HUMAN_TYPING_DELAY_SECONDS,
    )
    return Response(status_code=200, content="OK", media_type="text/plain")
