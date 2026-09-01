import logging
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.whatsapp_service import normalize_brazil_whatsapp_number

logger = logging.getLogger(__name__)

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _guess_mimetype(url: str) -> str:
    path = urlparse(url).path.lower()
    for suffix, mime in _MIME_BY_SUFFIX.items():
        if path.endswith(suffix):
            return mime
    return "image/jpeg"


def _guess_filename(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1].strip()
    if name and "." in name:
        return name[:120]
    return "foto.jpg"


class EvolutionClient:
    """Cliente HTTP da Evolution API v2 (`/message/sendText`, `/message/sendMedia`)."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = (settings.evolution_api_url or "").rstrip("/")
        self._api_key = (settings.evolution_api_key or "").strip()
        self._instance = (settings.evolution_instance or "").strip()

    def configured(self) -> bool:
        return bool(self._base_url and self._api_key and self._instance)

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._api_key,
            "Content-Type": "application/json",
        }

    def _endpoint(self, path: str) -> str:
        return f"{self._base_url}{path}/{self._instance}"

    def _number(self, to: str) -> str:
        return normalize_brazil_whatsapp_number(to)

    async def send_text(self, to: str, text: str, *, delay_ms: int = 1200) -> bool:
        if not self.configured():
            logger.error(
                "Evolution API não configurada "
                "(EVOLUTION_API_URL / EVOLUTION_API_KEY / EVOLUTION_INSTANCE)"
            )
            return False
        body_text = (text or "").strip()
        if not body_text:
            return False

        payload: dict[str, object] = {
            "number": self._number(to),
            "text": body_text[:4096],
            "linkPreview": False,
        }
        if delay_ms > 0:
            payload["delay"] = delay_ms
        return await self._post("/message/sendText", payload, "sendText")

    async def send_media(
        self,
        to: str,
        media_url: str,
        *,
        caption: str = "",
        delay_ms: int = 800,
    ) -> bool:
        if not self.configured():
            logger.error(
                "Evolution API não configurada — não foi possível enviar mídia"
            )
            return False
        link = (media_url or "").strip()
        if not link:
            logger.warning("URL de mídia vazia — envio ignorado")
            return False

        payload: dict[str, object] = {
            "number": self._number(to),
            "mediatype": "image",
            "mimetype": _guess_mimetype(link),
            "media": link,
            "fileName": _guess_filename(link),
        }
        caption_text = (caption or "").strip()
        if caption_text:
            payload["caption"] = caption_text[:1024]
        if delay_ms > 0:
            payload["delay"] = delay_ms
        return await self._post("/message/sendMedia", payload, "sendMedia")

    async def _post(self, path: str, payload: dict[str, object], op: str) -> bool:
        url = self._endpoint(path)
        timeout = httpx.Timeout(45.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            if response.status_code >= 400:
                logger.error(
                    "Evolution %s instance=%s HTTP %s: %s",
                    op,
                    self._instance,
                    response.status_code,
                    response.text[:500],
                )
                return False
        logger.info("Evolution %s ok instance=%s number=%s", op, self._instance, payload.get("number"))
        return True
