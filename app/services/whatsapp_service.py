import logging

import httpx

from app.config import Settings
from app.models.whatsapp import IncomingMessage, WebhookPayload

logger = logging.getLogger(__name__)


class WhatsAppService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        expected = (self._settings.whatsapp_verify_token or "").strip()
        received = (token or "").strip()
        if mode == "subscribe" and received and received == expected and challenge:
            return challenge
        logger.warning(
            "Falha na verificação do webhook WhatsApp (mode=%r token_match=%s challenge=%s)",
            mode,
            received == expected if received and expected else False,
            bool(challenge),
        )
        return None

    def parse_incoming_messages(self, payload: WebhookPayload) -> list[IncomingMessage]:
        messages: list[IncomingMessage] = []
        if payload.object != "whatsapp_business_account":
            return messages

        for entry in payload.entry:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for item in value.get("messages", []):
                    if item.get("type") != "text":
                        continue
                    text_body = item.get("text", {}).get("body")
                    if not text_body:
                        continue
                    messages.append(
                        IncomingMessage(
                            from_phone=item.get("from", ""),
                            message_id=item.get("id", ""),
                            text=text_body.strip(),
                            timestamp=item.get("timestamp"),
                        )
                    )
        return messages

    async def send_text_message(self, to_phone: str, text: str) -> None:
        if not self._settings.whatsapp_access_token or not self._settings.whatsapp_phone_number_id:
            logger.error("WhatsApp não configurado (token ou phone_number_id ausente)")
            return

        headers = {
            "Authorization": f"Bearer {self._settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4096]},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._settings.whatsapp_graph_url,
                headers=headers,
                json=body,
            )
            if response.status_code >= 400:
                logger.error(
                    "Erro ao enviar mensagem WhatsApp: %s %s",
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()

    async def mark_message_read(self, message_id: str) -> None:
        if not message_id or not self._settings.whatsapp_access_token:
            return

        url = (
            f"https://graph.facebook.com/{self._settings.whatsapp_api_version}"
            f"/{self._settings.whatsapp_phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self._settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(url, headers=headers, json=body)
