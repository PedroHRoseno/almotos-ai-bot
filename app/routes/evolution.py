import asyncio
import hmac
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

# Evolution / proxies variam o nome. Starlette já é case-insensitive.
_APIKEY_HEADER_NAMES = (
    "apikey",
    "api-key",
    "api_key",
    "x-api-key",
    "x-apikey",
    "x-evolution-apikey",
    "x-evolution-key",
)


def _get_evolution_chat_service() -> EvolutionChatService:
    settings = get_settings()
    return EvolutionChatService(
        settings=settings,
        evolution=EvolutionClient(settings),
        almotos_ai=AlmotosAiClient(settings),
    )


def _normalize_secret(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value).strip().strip('"').strip("'")
    lower = raw.lower()
    for prefix in ("bearer ", "apikey ", "api-key "):
        if lower.startswith(prefix):
            return raw[len(prefix) :].strip()
    return raw


def _keys_match(expected: str, received: str) -> bool:
    if not expected or not received:
        return False
    left = expected.encode("utf-8")
    right = received.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def _collect_received_keys(request: Request, payload: EvolutionWebhookPayload) -> list[str]:
    """Header `apikey` / `x-api-key` / Authorization e `apikey` do body (token da instância)."""
    found: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        cleaned = _normalize_secret(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            found.append(cleaned)

    for name in _APIKEY_HEADER_NAMES:
        add(request.headers.get(name))
    add(request.headers.get("authorization"))
    for name, value in request.headers.items():
        compact = name.lower().replace("-", "").replace("_", "")
        if "apikey" in compact or compact in {"authorization", "apikey"}:
            add(value)
    add(payload.apikey)
    return found


def _expected_keys(settings: Settings) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw in (settings.evolution_webhook_secret, settings.evolution_api_key):
        cleaned = _normalize_secret(raw)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            keys.append(cleaned)
    return keys


def _apikey_ok(
    settings: Settings,
    payload: EvolutionWebhookPayload,
    request: Request,
) -> bool:
    expected = _expected_keys(settings)
    if not expected:
        return True

    received = _collect_received_keys(request, payload)
    if any(_keys_match(exp, rec) for exp in expected for rec in received):
        return True

    auth_headers = sorted(
        {
            name.lower()
            for name in request.headers.keys()
            if "api" in name.lower() or name.lower() == "authorization"
        }
    )
    # Body da Evolution traz o token da instância; o header costuma ser a global key.
    # Sem match: em debug / auth não-estrita seguimos o fluxo e2e em vez de 401.
    if settings.debug or not settings.evolution_webhook_auth_required:
        logger.warning(
            "Webhook Evolution: apikey não conferiu (headers=%s, body_apikey=%s); "
            "processando assim mesmo (EVOLUTION_WEBHOOK_AUTH_REQUIRED=false)",
            auth_headers or "nenhum",
            "sim" if _normalize_secret(payload.apikey) else "não",
        )
        return True

    logger.warning(
        "Webhook Evolution rejeitado: apikey inválida (headers=%s, body_apikey=%s)",
        auth_headers or "nenhum",
        "sim" if _normalize_secret(payload.apikey) else "não",
    )
    return False


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
    if not _apikey_ok(settings, payload, request):
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
