from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_PROD_HINT = "https://api.almotoscaruaru.com.br"


def normalize_backend_base(raw: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    return value.rstrip("/")


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


class BackendClient:
    """Cliente HTTP do SoR (ADR-001). Sem Postgres neste processo."""

    def __init__(self, settings: Settings) -> None:
        self._base = normalize_backend_base(settings.almotos_backend_url)
        self._key = (settings.internal_api_key or "").strip()
        self._on_railway = bool((settings.railway_environment or "").strip())

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._key:
            headers["X-Internal-Key"] = self._key
        return headers

    def _configured(self) -> bool:
        if not self._base:
            logger.error("ALMOTOS_BACKEND_URL ausente")
            return False
        if self._on_railway and is_loopback_url(self._base):
            logger.error(
                "ALMOTOS_BACKEND_URL=%s no Railway aponta para este container. "
                "Defina a URL pública do SoR (ex.: %s) ou o domínio privado do serviço backend.",
                self._base,
                _PROD_HINT,
            )
            return False
        return True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response | None:
        if not self._configured():
            return None
        url = f"{self._base}{path}"
        timeout = httpx.Timeout(30.0, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.request(method, url, headers=headers or self._headers())
        except httpx.ConnectError:
            logger.error(
                "Não conectou em %s %s. Confira ALMOTOS_BACKEND_URL no serviço do bot "
                "(produção: %s). TCP recusado/DNS — não é 401 da API.",
                method,
                url,
                _PROD_HINT,
            )
            return None
        except httpx.TimeoutException:
            logger.error("Timeout em %s %s", method, url)
            return None

    async def list_pending_interests(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/vehicles/interests/pending")
        if response is None:
            return []
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
        response = await self._request(
            "GET",
            "/api/public/vehicles",
            headers={"Accept": "application/json"},
        )
        if response is None:
            return []
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
        response = await self._request(
            "PATCH",
            f"/vehicles/interests/{interest_id}/complete",
        )
        if response is None:
            return False
        if response.status_code >= 400:
            logger.error(
                "PATCH complete interest %s HTTP %s: %s",
                interest_id,
                response.status_code,
                response.text[:400],
            )
            return False
        return True
