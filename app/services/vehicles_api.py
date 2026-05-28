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
        token = self._settings.vehicles_api_token.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def fetch_available_vehicles(self) -> list[VehicleItem]:
        """Busca veículos na API principal (suporta resposta paginada ou lista)."""
        all_items: list[VehicleItem] = []
        page = 0
        page_size = self._settings.vehicles_api_page_size

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                params = {
                    "page": str(page),
                    "size": str(page_size),
                    "sort": "createdAt,desc",
                    "inStock": "true",
                }
                response = await client.get(
                    self._settings.vehicles_api_url,
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                data: Any = response.json()
                parsed = VehiclesPageResponse.from_api_json(data)
                all_items.extend(parsed.content)

                if isinstance(data, dict) and parsed.total_pages > 0:
                    if page + 1 >= parsed.total_pages:
                        break
                    page += 1
                    continue
                break

        # Catálogo público: apenas publicados, se o campo existir
        filtered = [
            v
            for v in all_items
            if v.in_stock is not False and (v.published is None or v.published is True)
        ]
        return filtered if filtered else all_items

    def format_inventory_for_llm(self, vehicles: list[VehicleItem]) -> str:
        if not vehicles:
            return (
                "Nenhum veículo disponível no estoque no momento. "
                "Informe ao cliente que a equipe pode ajudar em breve ou que ele pode ligar na loja."
            )

        lines = ["ESTOQUE ATUAL DE MOTOS DISPONÍVEIS:", ""]
        for i, v in enumerate(vehicles, start=1):
            km = (
                f"{v.kilometers_driven:,} km".replace(",", ".")
                if v.kilometers_driven is not None
                else "km não informado"
            )
            desc = f" — {v.description}" if v.description else ""
            plate = f" (placa {v.license_plate})" if v.license_plate else ""
            lines.append(
                f"{i}. {v.display_brand()} {v.display_model()} — "
                f"Ano {v.display_year()} — Cor {v.color or 'não informada'} — "
                f"{km}{plate}{desc}"
            )
        return "\n".join(lines)
