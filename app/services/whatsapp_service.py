import logging

import httpx

from app.config import Settings
from app.models.whatsapp import IncomingMessage, WebhookPayload

logger = logging.getLogger(__name__)


def normalize_brazil_whatsapp_number(phone: str) -> str:
    """
    Corrige o 9º dígito em números BR recebidos pelo webhook sem o nono dígito.

    Regra: 55 + DDD (2) + 8 dígitos = 12 chars → insere '9' após o DDD.
    Ex.: 558184424303 → 5581984424303
    """
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("55") and len(digits) == 12:
        normalized = digits[:4] + "9" + digits[4:]
        logger.info(
            "Número BR normalizado (9º dígito): %s → %s",
            digits,
            normalized,
        )
        return normalized
    return digits or phone.strip()


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

    async def send_text_message(self, to_phone: str, text: str) -> bool:
        if not self._settings.whatsapp_access_token or not self._settings.whatsapp_phone_number_id:
            logger.error("WhatsApp não configurado (token ou phone_number_id ausente)")
            return False

        recipient = normalize_brazil_whatsapp_number(to_phone)

        headers = {
            "Authorization": f"Bearer {self._settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
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
                    "Erro ao enviar mensagem WhatsApp para %s (normalizado: %s): HTTP %s %s",
                    to_phone,
                    recipient,
                    response.status_code,
                    response.text[:500],
                )
                return False
        return True

    async def send_image_message(self, to: str, image_url: str) -> bool:
        if not self._settings.whatsapp_access_token or not self._settings.whatsapp_phone_number_id:
            logger.error("WhatsApp não configurado (token ou phone_number_id ausente)")
            return False

        link = (image_url or "").strip()
        if not link:
            logger.warning("URL de imagem vazia — envio ignorado")
            return False

        recipient = normalize_brazil_whatsapp_number(to)

        headers = {
            "Authorization": f"Bearer {self._settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "image",
            "image": {"link": link},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._settings.whatsapp_graph_url,
                headers=headers,
                json=body,
            )
            if response.status_code >= 400:
                logger.error(
                    "Erro ao enviar imagem WhatsApp para %s (normalizado: %s): HTTP %s %s",
                    to,
                    recipient,
                    response.status_code,
                    response.text[:500],
                )
                return False
        return True

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
