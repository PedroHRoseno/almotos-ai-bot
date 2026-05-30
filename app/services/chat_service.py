import logging
import re
from datetime import datetime, timedelta
from typing import TypedDict

from app.config import Settings
from app.models.whatsapp import IncomingMessage
from app.services.openai_service import OpenAIService
from app.services.vehicles_api import VehiclesApiService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

_MAX_MESSAGES = 20
_MEMORY_TTL = timedelta(hours=24)
_MAX_PHOTOS_PER_REPLY = 3
_PHOTO_TAG_PATTERN = re.compile(r"\[ENVIAR_FOTO:([^\]]+)\]", re.IGNORECASE)
_FALLBACK_REPLY = (
    "Desculpe, tivemos um problema técnico. "
    "Tente novamente em alguns minutos ou entre em contato com nossa loja."
)


class ConversationMemoryEntry(TypedDict):
    last_update: datetime
    messages: list[dict[str, str]]


conversation_memory: dict[str, ConversationMemoryEntry] = {}


def extract_photo_tags(text: str) -> tuple[str, list[str]]:
    urls = [match.strip() for match in _PHOTO_TAG_PATTERN.findall(text) if match.strip()]
    clean_text = _PHOTO_TAG_PATTERN.sub("", text)
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()
    return clean_text, urls[:_MAX_PHOTOS_PER_REPLY]


def _get_or_create_memory(phone_number: str) -> ConversationMemoryEntry:
    memory = conversation_memory.get(phone_number)
    if memory is None:
        memory = {
            "last_update": datetime.now(),
            "messages": [],
        }
        conversation_memory[phone_number] = memory
        return memory

    if datetime.now() - memory["last_update"] > _MEMORY_TTL:
        logger.info(
            "Memória expirada (>24h inativo) para %s — contexto limpo",
            phone_number,
        )
        memory["messages"] = []

    return memory


def _save_assistant_reply(phone_number: str, assistant_text: str) -> None:
    memory = conversation_memory[phone_number]
    memory["messages"].append({"role": "assistant", "content": assistant_text})
    memory["last_update"] = datetime.now()
    memory["messages"] = memory["messages"][-_MAX_MESSAGES:]


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

    async def handle_incoming_message(self, message: IncomingMessage) -> None:
        phone = message.from_phone
        if not phone or not message.text:
            return

        try:
            await self._whatsapp.mark_message_read(message.message_id)

            memory = _get_or_create_memory(phone)
            memory["messages"].append({"role": "user", "content": message.text})

            vehicles = await self._vehicles_api.fetch_available_vehicles()
            inventory_text = self._vehicles_api.format_inventory_for_llm(vehicles)

            reply = await self._openai.generate_reply(
                inventory_text=inventory_text,
                conversation_messages=memory["messages"],
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
                assistant_content = clean_text or (
                    "Enviei as fotos solicitadas." if photos_sent else reply
                )
                _save_assistant_reply(phone, assistant_content)
            else:
                memory["messages"].pop()
                logger.error(
                    "Resposta gerada mas não enviada para %s. "
                    "Se o app Meta estiver em modo desenvolvimento, adicione o número "
                    "em WhatsApp → API Setup → To (números de teste).",
                    phone,
                )
        except Exception:
            logger.exception("Erro ao processar mensagem de %s", phone)
            if (
                phone in conversation_memory
                and conversation_memory[phone]["messages"]
                and conversation_memory[phone]["messages"][-1].get("role") == "user"
            ):
                conversation_memory[phone]["messages"].pop()
            await self._whatsapp.send_text_message(phone, _FALLBACK_REPLY)
