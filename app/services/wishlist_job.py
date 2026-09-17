from __future__ import annotations

import logging

from app.config import Settings
from app.services.backend_client import BackendClient
from app.services.whatsapp_service import WhatsAppService
from app.services.wishlist_match import first_matching_vehicle

logger = logging.getLogger(__name__)


async def run_wishlist_poll(settings: Settings) -> int:
    """Cruza interesses PENDING com o catálogo público e dispara o template.

    Só marca COMPLETED depois do envio com sucesso na Meta Cloud API.
    """
    backend = BackendClient(settings)
    whatsapp = WhatsAppService(settings)
    interests = await backend.list_pending_interests()
    if not interests:
        return 0
    vehicles = await backend.list_public_vehicles()
    if not vehicles:
        logger.info("Lista de espera: %s interesses, estoque público vazio", len(interests))
        return 0

    sent = 0
    for interest in interests:
        vehicle = first_matching_vehicle(interest, vehicles)
        if vehicle is None:
            continue
        interest_id = interest.get("id")
        phone = str(interest.get("contactPhone") or interest.get("contact_phone") or "")
        brand = str(interest.get("desiredBrand") or interest.get("desired_brand") or "")
        model = str(interest.get("desiredModel") or interest.get("desired_model") or "")
        if not interest_id or not phone:
            continue
        ok = await whatsapp.send_wishlist_notification(phone, brand, model)
        if not ok:
            continue
        if await backend.complete_interest(str(interest_id)):
            sent += 1
            logger.info("Lista de espera concluída id=%s modelo=%s %s", interest_id, brand, model)
        else:
            logger.error("Template enviado mas PATCH complete falhou id=%s", interest_id)
    return sent
