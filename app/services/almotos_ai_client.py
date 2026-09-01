import logging
from typing import Any

import httpx

from app.config import Settings
from app.services.whatsapp_format import unique_media_urls

logger = logging.getLogger(__name__)


class AlmotosAiClient:
    """Thin client do orquestrador (ADR-003). Sem OpenAI e sem Kotlin neste processo."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete(self, *, thread_id: str, text: str) -> dict[str, Any]:
        url = f"{self._settings.almotos_ai_url.rstrip('/')}/v1/chat"
        payload = {
            "channel": "whatsapp",
            "threadId": thread_id,
            "text": text,
            "stream": False,
        }
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            if response.status_code >= 400:
                logger.error(
                    "almotos-ai HTTP %s: %s",
                    response.status_code,
                    response.text[:400],
                )
                response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return {"text": str(data), "images": [], "handoff": False}
            images = data.get("images") or []
            if not isinstance(images, list):
                images = []

            return {
                "text": (data.get("text") or "").strip(),
                "images": unique_media_urls(
                    [u for u in images if isinstance(u, str) and u.strip()]
                ),
                "handoff": bool(data.get("handoff")),
            }
