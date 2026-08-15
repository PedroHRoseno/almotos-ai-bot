import logging

from app.config import Settings
from app.models.whatsapp import IncomingMessage
from app.services.almotos_ai_client import AlmotosAiClient
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

_FALLBACK_REPLY = (
    "Desculpe, tivemos um problema técnico. "
    "Tente novamente em alguns minutos ou entre em contato com nossa loja."
)


class ChatService:
    def __init__(
        self,
        settings: Settings,
        whatsapp: WhatsAppService,
        almotos_ai: AlmotosAiClient,
    ) -> None:
        self._settings = settings
        self._whatsapp = whatsapp
        self._almotos_ai = almotos_ai

    async def handle_incoming_message(self, message: IncomingMessage) -> None:
        phone = message.from_phone
        if not phone or not message.text:
            return

        try:
            await self._whatsapp.mark_message_read(message.message_id)
            result = await self._almotos_ai.complete(thread_id=phone, text=message.text)

            text = result.get("text") or ""
            images = result.get("images") or []
            text_sent = False
            if text:
                text_sent = await self._whatsapp.send_text_message(phone, text)

            photos_sent = 0
            for image_url in images:
                if await self._whatsapp.send_image_message(phone, image_url):
                    photos_sent += 1

            if not text_sent and not photos_sent:
                logger.error(
                    "Resposta gerada mas não enviada para %s. "
                    "Se o app Meta estiver em modo desenvolvimento, adicione o número "
                    "em WhatsApp → API Setup → To (números de teste).",
                    phone,
                )
        except Exception:
            logger.exception("Erro ao processar mensagem de %s", phone)
            await self._whatsapp.send_text_message(phone, _FALLBACK_REPLY)
