from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class BackendClient:
    """Cliente HTTP do SoR (ADR-001). Sem Postgres neste processo."""

    def __init__(self, settings: Settings) -> None:
        self._base = (settings.almotos_backend_url or "").rstrip("/")
        self._key = (settings.internal_api_key or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._key:
            headers["X-Internal-Key"] = self._key
        return headers

    def _configured(self) -> bool:
        if self._base:
            return True
        logger.error("ALMOTOS_BACKEND_URL ausente")
        return False

    async def list_pending_interests(self) -> list[dict[str, Any]]:
        if not self._configured():
            return []
        url = f"{self._base}/vehicles/interests/pending"
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=self._headers())
        if response.status_code >= 400:
            logger.error(
                "GET pending interests HTTP %s: %s",
                response.status_code,
                response.text[:400],
            )
            return []
        data = response.json()
        return data if isinstance(data, list) else []

    async def list_public_vehicles(self) -> list[dict[str, Any]]:
        if not self._configured():
            return []
        url = f"{self._base}/api/public/vehicles"
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            logger.error(
                "GET public vehicles HTTP %s: %s",
                response.status_code,
                response.text[:400],
            )
            return []
        data = response.json()
        return data if isinstance(data, list) else []

    async def complete_interest(self, interest_id: UUID | str) -> bool:
        if not self._configured():
            return False
        url = f"{self._base}/vehicles/interests/{interest_id}/complete"
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.patch(url, headers=self._headers())
        if response.status_code >= 400:
            logger.error(
                "PATCH complete interest %s HTTP %s: %s",
                interest_id,
                response.status_code,
                response.text[:400],
            )
            return False
        return True
