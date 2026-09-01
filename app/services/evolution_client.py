import logging
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.reply_guard import get_reply_guard, typing_delay_ms
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

    def _jid(self, to: str) -> str:
        number = self._number(to)
        if "@" in number:
            return number
        return f"{number}@s.whatsapp.net"

    async def mark_as_read(self, to: str, message_id: str | None = None) -> None:
        """Confirma leitura — humano lê antes de responder. Falha é ignorada."""
        if not self.configured() or not message_id:
            return
        payload = {
            "readMessages": [
                {
                    "remoteJid": self._jid(to),
                    "fromMe": False,
                    "id": str(message_id),
                }
            ]
        }
        await self._post("/chat/markMessageAsRead", payload, "markRead", timeout=12.0, quiet=True)

    async def send_presence(self, to: str, *, delay_ms: int, presence: str = "composing") -> None:
        """Mostra 'digitando…' no WhatsApp. Não deve derrubar o envio da mensagem."""
        if not self.configured() or delay_ms <= 0:
            return
        number = self._number(to)
        delay = max(800, min(int(delay_ms), 16000))
        payload: dict[str, object] = {
            "number": number,
            "delay": delay,
            "presence": presence,
            "options": {
                "delay": delay,
                "presence": presence,
                "number": number,
            },
        }
        await self._post("/chat/sendPresence", payload, "sendPresence", timeout=12.0, quiet=True)

    async def signal_reading(self, to: str, message_id: str | None = None) -> None:
        """Lê a mensagem e começa a 'digitar' enquanto a IA pensa."""
        if not self.configured() or not to:
            return
        await self.mark_as_read(to, message_id)
        await self.send_presence(to, delay_ms=typing_delay_ms("…", kind="text"))

    async def send_text(self, to: str, text: str, *, delay_ms: int | None = None) -> bool:
        if not self.configured():
            logger.error(
                "Evolution API não configurada "
                "(EVOLUTION_API_URL / EVOLUTION_API_KEY / EVOLUTION_INSTANCE)"
            )
            return False
        body_text = (text or "").strip()
        if not body_text:
            return False

        number = self._number(to)
        typing_ms = delay_ms if delay_ms is not None else typing_delay_ms(body_text)
        await self.send_presence(number, delay_ms=typing_ms)
        guard = get_reply_guard()
        await guard.pace(number, extra_seconds=typing_ms / 1000.0, kind="text")

        payload: dict[str, object] = {
            "number": number,
            "text": body_text[:4096],
            "linkPreview": False,
            "presence": "composing",
            "delay": min(max(typing_ms // 4, 400), 2500),
        }
        ok = await self._post("/message/sendText", payload, "sendText")
        if ok:
            guard.remember_outbound(number, body_text)
        return ok

    async def send_media(
        self,
        to: str,
        media_url: str,
        *,
        caption: str = "",
        delay_ms: int | None = None,
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

        number = self._number(to)
        caption_text = (caption or "").strip()
        typing_ms = delay_ms if delay_ms is not None else typing_delay_ms(caption_text, kind="media")
        await self.send_presence(number, delay_ms=typing_ms)
        guard = get_reply_guard()
        await guard.pace(number, extra_seconds=typing_ms / 1000.0, kind="media")

        payload: dict[str, object] = {
            "number": number,
            "mediatype": "image",
            "mimetype": _guess_mimetype(link),
            "media": link,
            "fileName": _guess_filename(link),
            "presence": "composing",
            "delay": min(max(typing_ms // 3, 600), 2800),
        }
        if caption_text:
            payload["caption"] = caption_text[:1024]
        ok = await self._post("/message/sendMedia", payload, "sendMedia")
        if ok:
            guard.remember_outbound(number, caption_text or "__media__")
        return ok

    async def _post(
        self,
        path: str,
        payload: dict[str, object],
        op: str,
        *,
        timeout: float = 45.0,
        quiet: bool = False,
    ) -> bool:
        url = self._endpoint(path)
        http_timeout = httpx.Timeout(timeout, connect=10.0)
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            if response.status_code >= 400:
                log = logger.debug if quiet else logger.error
                log(
                    "Evolution %s instance=%s HTTP %s: %s",
                    op,
                    self._instance,
                    response.status_code,
                    response.text[:500],
                )
                return False
        if not quiet:
            logger.info("Evolution %s ok instance=%s number=%s", op, self._instance, payload.get("number"))
        return True
