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


class ChatwootConversation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    status: str | None = None


class ChatwootWebhookPayload(BaseModel):
    """Payload do webhook AgentBot do Chatwoot (`message_created` e correlatos)."""

    model_config = ConfigDict(extra="ignore")

    event: str = ""
    message_type: str | None = None
    content: str | None = None
    conversation: ChatwootConversation | None = None
    sender: ChatwootSender | None = None
    private: bool = False

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

    def should_process_ai(self) -> bool:
        """Regra de ouro: só `message_created` incoming público entra na IA."""
        if self.event != "message_created":
            return False
        if self.conversation is None:
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
