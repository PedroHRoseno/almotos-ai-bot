from __future__ import annotations

import re
import unicodedata
from typing import Any

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_SEARCH_STOPWORDS = {"de", "da", "do", "das", "dos", "a", "o", "e", "em", "no", "na"}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", (value or "").strip().lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _tokens(value: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for part in _TOKEN_SPLIT.split(_fold(value)):
        if len(part) < 2 or part in _SEARCH_STOPWORDS or part in seen:
            continue
        seen.add(part)
        tokens.append(part)
    return tokens


def interest_matches_vehicle(interest: dict[str, Any], vehicle: dict[str, Any]) -> bool:
    """Match exato: todos os tokens de marca e modelo do interesse aparecem no veículo."""
    brand = str(interest.get("desiredBrand") or interest.get("desired_brand") or "")
    model = str(interest.get("desiredModel") or interest.get("desired_model") or "")
    v_brand = str(vehicle.get("brand") or "")
    v_model = str(vehicle.get("model") or vehicle.get("modelName") or "")
    brand_tokens = _tokens(brand)
    model_tokens = _tokens(model)
    if not brand_tokens or not model_tokens:
        return False
    hay_brand = _fold(v_brand)
    hay_all = f"{hay_brand} {_fold(v_model)}"
    return all(token in hay_brand for token in brand_tokens) and all(
        token in hay_all for token in model_tokens
    )


def first_matching_vehicle(
    interest: dict[str, Any], vehicles: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for vehicle in vehicles:
        if interest_matches_vehicle(interest, vehicle):
            return vehicle
    return None
