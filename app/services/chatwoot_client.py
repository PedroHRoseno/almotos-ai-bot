import logging

import httpx

from app.config import Settings
from app.services.reply_guard import contact_key, get_reply_guard

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Cliente HTTP da API REST do Chatwoot (caixa omnichannel)."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = (settings.chatwoot_base_url or "").rstrip("/")
        self._token = (settings.chatwoot_api_token or "").strip()
        self._account_id = settings.chatwoot_account_id

    def _headers(self) -> dict[str, str]:
        return {
            "api_access_token": self._token,
            "Content-Type": "application/json",
        }

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
        await guard.pace(pace_key)

        url = self._conversation_url(conversation_id, "messages")
        payload = {"content": body[:4096], "message_type": "outgoing"}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
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

    async def handoff_to_human(self, conversation_id: int) -> bool:
        """Abre a conversa para um atendente real (`status: open`)."""
        if not self._configured():
            return False

        url = self._conversation_url(conversation_id, "toggle_status")
        payload = {"status": "open"}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
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
            response = await client.post(url, headers=self._headers(), json=payload)
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
