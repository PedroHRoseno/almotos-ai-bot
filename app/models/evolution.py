from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

_TEXT_TYPES = frozenset(
    {
        "conversation",
        "extendedtextmessage",
        "extendedtext",
        "ephemeralmessage",
        "viewoncemessage",
    }
)
_MEDIA_TYPES = frozenset(
    {
        "imagemessage",
        "videomessage",
        "audiomessage",
        "documentmessage",
        "stickermessage",
        "ptt",
        "image",
        "video",
        "audio",
        "document",
        "sticker",
    }
)
_SKIP_JID_MARKERS = ("@g.us", "status@broadcast", "@broadcast")
_PHONE_JID_MARKERS = ("@s.whatsapp.net", "@c.us")
_UPSERT_EVENTS = frozenset(
    {
        "messages.upsert",
        "messages_upsert",
        "messagesupsert",
    }
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def _norm_event(event: str) -> str:
    return (event or "").strip().lower().replace("-", "_")


def _norm_type(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", "").replace(" ", "")


def parse_remote_jid(value: str | None) -> tuple[str | None, str | None]:
    """Extrai `(jid, número)` de um remoteJid/identifier/telefone.

    Retorna `(None, None)` para grupo, status ou valor vazio.
    """
    raw = (value or "").strip()
    if not raw:
        return None, None
    lowered = raw.lower()
    if any(marker in lowered for marker in _SKIP_JID_MARKERS):
        return None, None

    jid = raw
    if "@" not in raw:
        digits = _digits(raw)
        if not digits:
            return None, None
        jid = f"{digits}@s.whatsapp.net"
        return jid, digits

    local, _, domain = raw.partition("@")
    if domain.lower() in {"s.whatsapp.net", "c.us"}:
        digits = _digits(local)
        return (jid, digits) if digits else (None, None)

    # @lid: o telefone costuma vir em remoteJidAlt; só aceita dígitos se parecer número.
    digits = _digits(local)
    if len(digits) >= 10:
        return jid, digits
    return jid, None


def _message_body(message: dict[str, Any]) -> tuple[str, str | None]:
    """Retorna `(texto_ou_legenda, tipo_de_mídia|None)`."""
    if not message:
        return "", None

    inner = message
    for wrapper in ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2"):
        wrapped = _as_dict(inner.get(wrapper)).get("message")
        if isinstance(wrapped, dict):
            inner = wrapped
            break

    conversation = inner.get("conversation")
    if isinstance(conversation, str) and conversation.strip():
        return conversation.strip(), None

    extended = _as_dict(inner.get("extendedTextMessage"))
    extended_text = extended.get("text")
    if isinstance(extended_text, str) and extended_text.strip():
        return extended_text.strip(), None

    for key, media_kind in (
        ("imageMessage", "image"),
        ("videoMessage", "video"),
        ("documentMessage", "document"),
        ("audioMessage", "audio"),
        ("stickerMessage", "sticker"),
    ):
        block = _as_dict(inner.get(key))
        if not block and key not in inner:
            continue
        if key in inner or block:
            caption = block.get("caption")
            text = caption.strip() if isinstance(caption, str) else ""
            return text, media_kind

    return "", None


def _key_candidates(key: dict[str, Any], fallback_sender: str | None) -> list[str]:
    """Ordem: JID de telefone, alt, PN, sender da raiz."""
    values: list[str] = []
    for field in ("remoteJid", "remoteJidAlt", "senderPn", "participant", "participantAlt"):
        item = key.get(field)
        if isinstance(item, str) and item.strip():
            values.append(item.strip())
    if fallback_sender:
        values.append(fallback_sender)
    # Prioriza JID com número visível.
    phones = [v for v in values if any(m in v.lower() for m in _PHONE_JID_MARKERS) or "@" not in v]
    lids = [v for v in values if v not in phones]
    return phones + lids


class EvolutionIncomingMessage(BaseModel):
    remote_jid: str
    number: str
    message_id: str
    text: str = ""
    kind: Literal["text", "media"]
    media_type: str | None = None
    from_me: bool = False
    push_name: str | None = None


class EvolutionWebhookPayload(BaseModel):
    """Payload do webhook Evolution (`MESSAGES_UPSERT` e equivalentes)."""

    model_config = ConfigDict(extra="ignore")

    event: str = ""
    instance: str | None = None
    data: Any = None
    sender: str | None = None
    apikey: str | None = Field(
        default=None,
        validation_alias=AliasChoices("apikey", "apiKey", "api_key"),
    )

    def is_upsert(self) -> bool:
        if not self.event:
            return True
        return _norm_event(self.event).replace(".", "_") in _UPSERT_EVENTS

    def incoming_messages(self) -> list[EvolutionIncomingMessage]:
        if not self.is_upsert():
            return []
        out: list[EvolutionIncomingMessage] = []
        for item in _iter_data_items(self.data):
            parsed = _parse_item(item, self.sender)
            if parsed is not None:
                out.append(parsed)
        return out


def parse_evolution_payload(body: dict[str, Any]) -> list[EvolutionIncomingMessage]:
    payload = EvolutionWebhookPayload.model_validate(body)
    messages = payload.incoming_messages()
    if messages:
        return messages
    if "key" in body or "message" in body:
        parsed = _parse_item(body, payload.sender)
        return [parsed] if parsed else []
    return []


def number_from_contact_fields(*values: str | None) -> tuple[str | None, str | None]:
    """Tenta remoteJid/telefone a partir de campos do Chatwoot ou Evolution."""
    for value in values:
        jid, number = parse_remote_jid(value)
        if jid and number:
            return jid, number
    for value in values:
        jid, number = parse_remote_jid(value)
        if jid:
            return jid, number
    return None, None


def _iter_data_items(data: Any):
    if data is None:
        return
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(data, dict):
        return
    if "key" in data or "message" in data:
        yield data
        return
    messages = data.get("messages")
    if isinstance(messages, list):
        for item in messages:
            if isinstance(item, dict):
                yield item


def _parse_item(item: dict[str, Any], fallback_sender: str | None) -> EvolutionIncomingMessage | None:
    key = _as_dict(item.get("key"))
    from_me = bool(key.get("fromMe") or item.get("fromMe"))
    if from_me:
        return None

    jid: str | None = None
    number: str | None = None
    for candidate in _key_candidates(key, fallback_sender):
        jid, number = parse_remote_jid(candidate)
        if jid and number:
            break
        if jid and not number:
            # LID sem dígitos úteis — continua procurando um telefone.
            continue
    if not jid:
        return None
    if not number:
        return None

    message = _as_dict(item.get("message"))
    text, media_from_body = _message_body(message)
    raw_type = item.get("messageType") or item.get("type")
    type_norm = _norm_type(str(raw_type) if raw_type else "")

    kind: Literal["text", "media"]
    media_type = media_from_body
    if media_from_body or type_norm in _MEDIA_TYPES:
        kind = "media"
        if not media_type:
            if "image" in type_norm:
                media_type = "image"
            elif "video" in type_norm:
                media_type = "video"
            elif "audio" in type_norm or type_norm == "ptt":
                media_type = "audio"
            elif "document" in type_norm:
                media_type = "document"
            elif "sticker" in type_norm:
                media_type = "sticker"
            else:
                media_type = "image"
    elif type_norm in _TEXT_TYPES or text:
        kind = "text"
    else:
        return None

    message_id = str(key.get("id") or item.get("id") or "")
    push_name = item.get("pushName") or item.get("pushname")
    if not isinstance(push_name, str):
        push_name = None

    return EvolutionIncomingMessage(
        remote_jid=jid,
        number=number,
        message_id=message_id,
        text=text,
        kind=kind,
        media_type=media_type if kind == "media" else None,
        from_me=False,
        push_name=push_name,
    )
