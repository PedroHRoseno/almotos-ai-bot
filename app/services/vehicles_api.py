import logging
from typing import Any

import httpx

from app.config import Settings
from app.models.vehicles import VehicleItem, VehiclesPageResponse

logger = logging.getLogger(__name__)


class VehiclesApiService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        token = (self._settings.vehicles_api_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def fetch_available_vehicles(self) -> list[VehicleItem]:
        """Busca veículos na API principal. Não lança exceção — retorna [] em falha."""
        url = self._settings.vehicles_api_url.strip()
        token = (self._settings.vehicles_api_token or "").strip()

        # Endpoint público não precisa de JWT
        if "/api/public/" in url or not token:
            return await self._fetch_public_list(url)

        items = await self._fetch_paginated_admin(url)
        if items:
            return items

        # Fallback: se /vehicles retornou 401, tenta catálogo público
        public_url = url.replace("/vehicles", "/api/public/vehicles")
        if public_url != url:
            logger.warning("Fallback para catálogo público: %s", public_url)
            return await self._fetch_public_list(public_url)

        return []

    async def _fetch_public_list(self, url: str) -> list[VehicleItem]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers={"Accept": "application/json"})
                if response.status_code >= 400:
                    logger.error(
                        "API veículos (público) %s → HTTP %s: %s",
                        url,
                        response.status_code,
                        response.text[:300],
                    )
                    return []
                data: Any = response.json()
                parsed = VehiclesPageResponse.from_api_json(data)
                logger.info("Estoque público carregado: %s veículo(s)", len(parsed.content))
                return parsed.content
        except Exception:
            logger.exception("Falha ao buscar estoque público em %s", url)
            return []

    async def _fetch_paginated_admin(self, url: str) -> list[VehicleItem]:
        all_items: list[VehicleItem] = []
        page = 0
        page_size = self._settings.vehicles_api_page_size

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    params = {
                        "page": str(page),
                        "size": str(page_size),
                        "sort": "createdAt,desc",
                        "inStock": "true",
                    }
                    response = await client.get(
                        url,
                        params=params,
                        headers=self._headers(),
                    )
                    if response.status_code == 401:
                        logger.error(
                            "API veículos (admin) 401 — configure VEHICLES_API_TOKEN ou use "
                            "VEHICLES_API_URL=https://api.almotoscaruaru.com.br/api/public/vehicles"
                        )
                        return []
                    if response.status_code >= 400:
                        logger.error(
                            "API veículos (admin) HTTP %s: %s",
                            response.status_code,
                            response.text[:300],
                        )
                        return []

                    data: Any = response.json()
                    parsed = VehiclesPageResponse.from_api_json(data)
                    all_items.extend(parsed.content)

                    if isinstance(data, dict) and parsed.total_pages > 0:
                        if page + 1 >= parsed.total_pages:
                            break
                        page += 1
                        continue
                    break
        except Exception:
            logger.exception("Falha ao buscar estoque admin em %s", url)
            return []

        filtered = [
            v
            for v in all_items
            if v.in_stock is not False and (v.published is None or v.published is True)
        ]
        result = filtered if filtered else all_items
        logger.info("Estoque admin carregado: %s veículo(s)", len(result))
        return result

    def format_inventory_for_llm(self, vehicles: list[VehicleItem]) -> str:
        if not vehicles:
            return (
                "Nenhum veículo disponível no estoque no momento. "
                "Informe ao cliente que a equipe pode ajudar em breve ou que ele pode ligar na loja."
            )

        lines = [
            "ESTOQUE ATUAL (use o formato de listagem com emojis ao responder ao cliente):",
            "",
        ]
        for v in vehicles:
            model = f"{v.display_brand()} {v.display_model()}".strip()
            photos = v.photo_urls(3)
            photo_info = " | ".join(f"[IMAGEM: {url}]" for url in photos) if photos else "sem fotos"
            lines.extend(
                [
                    f"🏍️ {model}",
                    f"📅 Ano: {v.display_year()} | 🎨 Cor: {v.color or 'não informada'}",
                    f"Fotos disponíveis: {photo_info}",
                    "",
                ]
            )
        return "\n".join(lines).strip()
