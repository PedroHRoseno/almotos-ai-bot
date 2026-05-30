import logging
import re
from collections import defaultdict

from app.config import Settings
from app.models.whatsapp import IncomingMessage
from app.services.openai_service import OpenAIService
from app.services.vehicles_api import VehiclesApiService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

_MAX_HISTORY = 6
_MAX_PHOTOS_PER_REPLY = 3
_PHOTO_TAG_PATTERN = re.compile(r"\[ENVIAR_FOTO:([^\]]+)\]", re.IGNORECASE)
_FALLBACK_REPLY = (
    "Desculpe, tivemos um problema técnico. "
    "Tente novamente em alguns minutos ou entre em contato com nossa loja."
)


def extract_photo_tags(text: str) -> tuple[str, list[str]]:
    urls = [match.strip() for match in _PHOTO_TAG_PATTERN.findall(text) if match.strip()]
    clean_text = _PHOTO_TAG_PATTERN.sub("", text)
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()
    return clean_text, urls[:_MAX_PHOTOS_PER_REPLY]


class ChatService:
    def __init__(
        self,
        settings: Settings,
        whatsapp: WhatsAppService,
        vehicles_api: VehiclesApiService,
        openai: OpenAIService,
    ) -> None:
        self._settings = settings
        self._whatsapp = whatsapp
        self._vehicles_api = vehicles_api
        self._openai = openai
        self._history: dict[str, list[dict[str, str]]] = defaultdict(list)

    async def handle_incoming_message(self, message: IncomingMessage) -> None:
        phone = message.from_phone
        if not phone or not message.text:
            return

        try:
            await self._whatsapp.mark_message_read(message.message_id)

            vehicles = await self._vehicles_api.fetch_available_vehicles()
            inventory_text = self._vehicles_api.format_inventory_for_llm(vehicles)

            history = self._history[phone][-_MAX_HISTORY:]
            reply = await self._openai.generate_reply(
                user_message=message.text,
                inventory_text=inventory_text,
                conversation_history=history,
            )

            clean_text, photo_urls = extract_photo_tags(reply)
            text_sent = False
            if clean_text:
                text_sent = await self._whatsapp.send_text_message(phone, clean_text)

            photos_sent = 0
            for image_url in photo_urls:
                if await self._whatsapp.send_image_message(phone, image_url):
                    photos_sent += 1

            if text_sent or photos_sent:
                history_text = clean_text or (
                    "Enviei as fotos solicitadas." if photos_sent else reply
                )
                self._append_history(phone, message.text, history_text)
            else:
                logger.error(
                    "Resposta gerada mas não enviada para %s. "
                    "Se o app Meta estiver em modo desenvolvimento, adicione o número "
                    "em WhatsApp → API Setup → To (números de teste).",
                    phone,
                )
        except Exception:
            logger.exception("Erro ao processar mensagem de %s", phone)
            await self._whatsapp.send_text_message(phone, _FALLBACK_REPLY)

    def _append_history(self, phone: str, user_text: str, assistant_text: str) -> None:
        hist = self._history[phone]
        hist.append({"role": "user", "content": user_text})
        hist.append({"role": "assistant", "content": assistant_text})
        if len(hist) > _MAX_HISTORY:
            self._history[phone] = hist[-_MAX_HISTORY:]
