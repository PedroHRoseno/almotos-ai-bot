import logging
from collections import defaultdict

from app.config import Settings
from app.models.whatsapp import IncomingMessage
from app.services.openai_service import OpenAIService
from app.services.vehicles_api import VehiclesApiService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

_MAX_HISTORY = 6
_FALLBACK_REPLY = (
    "Desculpe, tivemos um problema técnico. "
    "Tente novamente em alguns minutos ou entre em contato com nossa loja."
)


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

            sent = await self._whatsapp.send_text_message(phone, reply)
            if sent:
                self._append_history(phone, message.text, reply)
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
