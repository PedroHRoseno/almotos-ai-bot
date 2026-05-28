from typing import Any

from pydantic import BaseModel, Field


class WebhookVerifyParams(BaseModel):
    hub_mode: str = Field(alias="hub.mode")
    hub_verify_token: str = Field(alias="hub.verify_token")
    hub_challenge: str = Field(alias="hub.challenge")


class IncomingMessage(BaseModel):
    """Mensagem de texto recebida do cliente via WhatsApp."""

    from_phone: str
    message_id: str
    text: str
    timestamp: str | None = None


class WebhookPayload(BaseModel):
    """Payload bruto da Meta (estrutura parcial para validação leve)."""

    object: str | None = None
    entry: list[dict[str, Any]] = Field(default_factory=list)
