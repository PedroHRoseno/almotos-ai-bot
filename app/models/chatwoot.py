from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

_INCOMING = {0, "0", "incoming"}
_OUTGOING = {1, "1", "outgoing"}


def normalize_message_type(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if value in _INCOMING:
        return "incoming"
    if value in _OUTGOING:
        return "outgoing"
    return str(value).strip().lower()


class ChatwootSender(BaseModel):
    """Remetente do AgentBot (contato, agente ou o próprio bot)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None
    type: str | None = None
    phone_number: str | None = None
    identifier: str | None = None


class ChatwootConversation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    status: str | None = None
    meta: dict[str, Any] | None = None
    additional_attributes: dict[str, Any] | None = None


class ChatwootWebhookPayload(BaseModel):
    """Payload do webhook AgentBot do Chatwoot (`message_created` e correlatos)."""

    model_config = ConfigDict(extra="ignore")

    event: str = ""
    message_type: str | None = None
    content: str | None = None
    content_type: str | None = None
    conversation: ChatwootConversation | None = None
    sender: ChatwootSender | None = None
    private: bool = False
    attachments: list[Any] | None = None

    @field_validator("message_type", mode="before")
    @classmethod
    def _normalize_message_type(cls, value: Any) -> str | None:
        return normalize_message_type(value)

    @property
    def is_outgoing(self) -> bool:
        return self.message_type == "outgoing"

    @property
    def is_incoming(self) -> bool:
        return self.message_type == "incoming"

    def is_with_human(self) -> bool:
        """Conversa já aberta para um atendente — o bot não deve responder."""
        if self.conversation is None:
            return False
        return (self.conversation.status or "").strip().lower() == "open"

    def should_process_ai(self) -> bool:
        """Regra de ouro: só `message_created` incoming público entra na IA."""
        if self.event != "message_created":
            return False
        if self.conversation is None:
            return False
        if self.is_with_human():
            return False
        if self.is_outgoing or not self.is_incoming:
            return False
        if self.private:
            return False
        if not (self.content or "").strip():
            return False
        if self.sender and (self.sender.type or "").lower() == "agent_bot":
            return False
        return True

    def whatsapp_number(self) -> str | None:
        """Telefone/remoteJid do contato (Evolution/WhatsApp via Chatwoot)."""
        from app.models.evolution import number_from_contact_fields

        meta_sender: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        if self.conversation:
            if isinstance(self.conversation.meta, dict):
                raw = self.conversation.meta.get("sender") or {}
                if isinstance(raw, dict):
                    meta_sender = raw
            if isinstance(self.conversation.additional_attributes, dict):
                extra = self.conversation.additional_attributes

        _, number = number_from_contact_fields(
            self.sender.phone_number if self.sender else None,
            self.sender.identifier if self.sender else None,
            str(meta_sender.get("phone_number") or "") or None,
            str(meta_sender.get("identifier") or "") or None,
            str(extra.get("source_id") or "") or None,
        )
        return number
