"""Anti-loop de WhatsApp/Chatwoot.

Impede o bot de processar o próprio eco, mensagens de agente e o mesmo
evento chegando por Chatwoot + Evolution. Sem pacing: a entrega no canal
oficial (Chatwoot → Meta Cloud API) não precisa simular digitação.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Iterable

logger = logging.getLogger(__name__)

_SEEN_TTL_SECONDS = 180.0
_OUTBOUND_TTL_SECONDS = 180.0
_BUCKET_SECONDS = 20
_WS = re.compile(r"\s+")


def _norm_text(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def _digits_br(raw: str) -> str:
    digits = "".join(c for c in raw if c.isdigit())
    if digits.startswith("55") and len(digits) == 12:
        return digits[:4] + "9" + digits[4:]
    return digits


def content_fingerprint(text: str) -> str:
    normalized = _norm_text(text)
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def contact_key(*candidates: str | None) -> str:
    for raw in candidates:
        if not raw:
            continue
        digits = _digits_br(str(raw))
        if len(digits) >= 10:
            return digits
        stripped = str(raw).strip()
        if stripped:
            return stripped
    return ""


def time_bucket(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // _BUCKET_SECONDS)


class ReplyGuard:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._seen: dict[str, float] = {}
        self._outbound: dict[str, list[tuple[float, str]]] = {}

    def _prune(self, now: float) -> None:
        stale_seen = [k for k, ts in self._seen.items() if now - ts > _SEEN_TTL_SECONDS]
        for k in stale_seen:
            del self._seen[k]
        for key, items in list(self._outbound.items()):
            kept = [(ts, txt) for ts, txt in items if now - ts <= _OUTBOUND_TTL_SECONDS]
            if kept:
                self._outbound[key] = kept[-12:]
            else:
                del self._outbound[key]

    def _is_echo_unlocked(self, key: str, text: str) -> bool:
        needle = _norm_text(text)
        if not needle or not key:
            return False
        now = time.monotonic()
        for ts, sent in self._outbound.get(key, []):
            if now - ts > _OUTBOUND_TTL_SECONDS:
                continue
            if needle == sent or needle[:80] == sent[:80]:
                return True
        return False

    async def claim_inbound(
        self,
        *,
        contact_key: str,
        fingerprints: Iterable[str],
        text: str,
    ) -> bool:
        """True = este processo deve responder. False = eco/duplicata."""
        key = contact_key or "unknown"
        fps = [fp for fp in fingerprints if fp]
        async with self._lock:
            now = time.monotonic()
            self._prune(now)
            if self._is_echo_unlocked(key, text):
                logger.info("Inbound ignorado (eco do próprio bot) key=%s", key)
                return False
            for fp in fps:
                if fp in self._seen:
                    logger.info("Inbound ignorado (duplicado) fp=%s key=%s", fp, key)
                    return False
            for fp in fps:
                self._seen[fp] = now
            return True

    def remember_outbound(self, contact_key: str, text: str) -> None:
        key = contact_key or "unknown"
        needle = _norm_text(text)
        if not needle:
            return
        now = time.monotonic()
        bucket = self._outbound.setdefault(key, [])
        bucket.append((now, needle))
        self._outbound[key] = bucket[-12:]


_guard: ReplyGuard | None = None


def get_reply_guard() -> ReplyGuard:
    global _guard
    if _guard is None:
        _guard = ReplyGuard()
    return _guard


def shared_fingerprints(*, contact_key: str, text: str, source_id: str | None) -> list[str]:
    fps: list[str] = []
    digest = content_fingerprint(text)
    bucket = time_bucket()
    if source_id:
        fps.append(f"id:{source_id}")
    if contact_key and digest:
        fps.append(f"x:{contact_key}:{digest}:{bucket}")
    return fps
