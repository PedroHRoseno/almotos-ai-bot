"""Buffer em memória para debounce de mensagens Chatwoot (por conversation_id).

Não é persistência de estoque (ADR-001): é só estado efêmero do processo FastAPI
para juntar mensagens rápidas antes de chamar o orquestrador.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.models.chatwoot import ChatwootWebhookPayload

logger = logging.getLogger(__name__)


@dataclass
class _Slot:
    texts: list[str] = field(default_factory=list)
    payload: ChatwootWebhookPayload | None = None
    updated_at: float = 0.0
    generation: int = 0


class ConversationMessageBuffer:
    def __init__(self, *, window_seconds: float = 4.0) -> None:
        self._window = max(0.1, float(window_seconds))
        self._lock = asyncio.Lock()
        self._slots: dict[int, _Slot] = {}

    async def push(
        self,
        conversation_id: int,
        text: str,
        payload: ChatwootWebhookPayload,
    ) -> int:
        """Concatena o texto, atualiza o timestamp e devolve a geração atual."""
        body = (text or "").strip()
        async with self._lock:
            slot = self._slots.get(conversation_id)
            if slot is None:
                slot = _Slot()
                self._slots[conversation_id] = slot
            if body:
                slot.texts.append(body)
            slot.payload = payload
            slot.updated_at = time.monotonic()
            slot.generation += 1
            logger.info(
                "Buffer Chatwoot conversa=%s gen=%s partes=%s",
                conversation_id,
                slot.generation,
                len(slot.texts),
            )
            return slot.generation

    async def seconds_until_idle(self, conversation_id: int, generation: int) -> float | None:
        """None = waiter obsoleto. 0 = já pode flushar. >0 = falta na janela."""
        async with self._lock:
            slot = self._slots.get(conversation_id)
            if slot is None or slot.generation != generation:
                return None
            elapsed = time.monotonic() - slot.updated_at
            return max(0.0, self._window - elapsed)

    async def take_if_idle(
        self,
        conversation_id: int,
        generation: int,
    ) -> tuple[str, ChatwootWebhookPayload] | None:
        """Só o waiter da geração vigente flushes — evita dupla chamada à IA."""
        async with self._lock:
            slot = self._slots.get(conversation_id)
            if slot is None or slot.payload is None:
                return None
            if slot.generation != generation:
                logger.debug(
                    "Buffer Chatwoot conversa=%s waiter gen=%s obsoleto (atual=%s)",
                    conversation_id,
                    generation,
                    slot.generation,
                )
                return None
            elapsed = time.monotonic() - slot.updated_at
            if elapsed + 0.05 < self._window:
                logger.debug(
                    "Buffer Chatwoot conversa=%s ainda na janela elapsed=%.2fs",
                    conversation_id,
                    elapsed,
                )
                return None
            text = "\n".join(slot.texts).strip()
            payload = slot.payload
            del self._slots[conversation_id]
            if not text:
                return None
            logger.info(
                "Buffer Chatwoot flush conversa=%s gen=%s chars=%s",
                conversation_id,
                generation,
                len(text),
            )
            return text, payload


_buffer: ConversationMessageBuffer | None = None


def get_message_buffer() -> ConversationMessageBuffer:
    global _buffer
    if _buffer is None:
        from app.config import get_settings

        _buffer = ConversationMessageBuffer(
            window_seconds=get_settings().chatwoot_debounce_seconds
        )
    return _buffer
