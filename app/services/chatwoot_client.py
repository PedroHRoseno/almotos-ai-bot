import logging
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.reply_guard import contact_key, get_reply_guard

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


class ChatwootClient:
    """Cliente HTTP da API REST do Chatwoot (caixa omnichannel)."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = (settings.chatwoot_base_url or "").rstrip("/")
        self._token = (settings.chatwoot_api_token or "").strip()
        self._account_id = settings.chatwoot_account_id

    def _auth_headers(self) -> dict[str, str]:
        return {"api_access_token": self._token}

    def _json_headers(self) -> dict[str, str]:
        return {**self._auth_headers(), "Content-Type": "application/json"}

    def _conversation_url(self, conversation_id: int, suffix: str) -> str:
        return (
            f"{self._base_url}/api/v1/accounts/{self._account_id}"
            f"/conversations/{conversation_id}/{suffix}"
        )

    def _configured(self) -> bool:
        if self._base_url and self._token:
            return True
        logger.error("Chatwoot não configurado (CHATWOOT_BASE_URL ou CHATWOOT_API_TOKEN ausente)")
        return False

    async def send_message(
        self,
        conversation_id: int,
        text: str,
        *,
        whatsapp_number: str | None = None,
        extra_seconds: float = 0.0,
    ) -> bool:
        """POST outgoing na conversa — o Chatwoot entrega no canal (WA/widget/etc.)."""
        if not self._configured():
            return False
        body = (text or "").strip()
        if not body:
            logger.warning("send_message ignorado: conteúdo vazio (conversation_id=%s)", conversation_id)
            return False

        pace_key = contact_key(whatsapp_number) or f"cw:{conversation_id}"
        guard = get_reply_guard()
        await guard.pace(pace_key, extra_seconds=extra_seconds, kind="text")

        url = self._conversation_url(conversation_id, "messages")
        payload = {"content": body[:4096], "message_type": "outgoing"}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=self._json_headers(), json=payload)
            if response.status_code >= 400:
                logger.error(
                    "Chatwoot send_message conversation=%s HTTP %s: %s",
                    conversation_id,
                    response.status_code,
                    response.text[:500],
                )
                return False
        guard.remember_outbound(pace_key, body)
        logger.info("Chatwoot: mensagem enviada na conversa %s", conversation_id)
        return True

    async def send_attachment(
        self,
        conversation_id: int,
        media_url: str,
        *,
        caption: str = "",
        whatsapp_number: str | None = None,
        extra_seconds: float = 0.0,
    ) -> bool:
        """POST outgoing com `attachments[]` (multipart) — a caixa entrega a imagem no WhatsApp.

        A API do Chatwoot não aceita URL no JSON de texto: baixa a URL pública do
        catálogo e envia o arquivo como anexo, com a legenda em `content`.
        """
        if not self._configured():
            return False
        link = (media_url or "").strip()
        if not link:
            logger.warning(
                "send_attachment ignorado: URL vazia (conversation_id=%s)", conversation_id
            )
            return False

        pace_key = contact_key(whatsapp_number) or f"cw:{conversation_id}"
        guard = get_reply_guard()
        await guard.pace(pace_key, extra_seconds=extra_seconds, kind="media")

        timeout = httpx.Timeout(45.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                media_response = await client.get(link)
            except httpx.HTTPError:
                logger.exception(
                    "Chatwoot send_attachment: falha ao baixar mídia conversation=%s url=%s",
                    conversation_id,
                    link[:180],
                )
                return False
            if media_response.status_code >= 400 or not media_response.content:
                logger.error(
                    "Chatwoot send_attachment: download HTTP %s conversation=%s url=%s",
                    media_response.status_code,
                    conversation_id,
                    link[:180],
                )
                return False

            content_type = (media_response.headers.get("content-type") or "").split(";")[0].strip()
            if not content_type.startswith("image/"):
                content_type = _guess_mimetype(link)
            filename = _guess_filename(link)
            caption_text = (caption or "").strip()[:4096]
            url = self._conversation_url(conversation_id, "messages")
            data = {
                "content": caption_text,
                "message_type": "outgoing",
                "private": "false",
                "file_type": "image",
            }
            files = [("attachments[]", (filename, media_response.content, content_type))]
            response = await client.post(
                url, headers=self._auth_headers(), data=data, files=files
            )
            if response.status_code >= 400:
                logger.error(
                    "Chatwoot send_attachment conversation=%s HTTP %s: %s",
                    conversation_id,
                    response.status_code,
                    response.text[:500],
                )
                return False

        guard.remember_outbound(pace_key, caption_text or "__media__")
        logger.info(
            "Chatwoot: anexo enviado na conversa %s file=%s", conversation_id, filename
        )
        return True

    async def handoff_to_human(self, conversation_id: int) -> bool:
        """Abre a conversa para um atendente real (`status: open`)."""
        if not self._configured():
            return False

        url = self._conversation_url(conversation_id, "toggle_status")
        payload = {"status": "open"}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=self._json_headers(), json=payload)
            if response.status_code >= 400:
                logger.error(
                    "Chatwoot handoff_to_human conversation=%s HTTP %s: %s",
                    conversation_id,
                    response.status_code,
                    response.text[:500],
                )
                return False
        logger.info("Chatwoot: conversa %s transferida para humano (status=open)", conversation_id)
        return True

    async def send_private_note(self, conversation_id: int, text: str) -> bool:
        """Nota interna na conversa — o cliente não vê."""
        if not self._configured():
            return False
        body = (text or "").strip()
        if not body:
            return False

        url = self._conversation_url(conversation_id, "messages")
        payload = {"content": body[:4096], "message_type": "outgoing", "private": True}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=self._json_headers(), json=payload)
            if response.status_code >= 400:
                logger.error(
                    "Chatwoot send_private_note conversation=%s HTTP %s: %s",
                    conversation_id,
                    response.status_code,
                    response.text[:500],
                )
                return False
        logger.info("Chatwoot: nota privada na conversa %s", conversation_id)
        return True
