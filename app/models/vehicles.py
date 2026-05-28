from typing import Any

from pydantic import BaseModel, Field


class VehicleItem(BaseModel):
    license_plate: str | None = Field(default=None, alias="licensePlate")
    brand: str | None = None
    model_name: str | None = Field(default=None, alias="modelName")
    model: str | None = None
    manufacture_year: int | None = Field(default=None, alias="manufactureYear")
    model_year: int | None = Field(default=None, alias="modelYear")
    year: int | None = None
    color: str | None = None
    kilometers_driven: int | None = Field(default=None, alias="kilometersDriven")
    status: str | None = None
    in_stock: bool | None = Field(default=None, alias="inStock")
    published: bool | None = None
    description: str | None = None

    model_config = {"populate_by_name": True, "extra": "ignore"}

    def display_brand(self) -> str:
        raw = self.brand or ""
        if isinstance(raw, str):
            return raw.replace("_", " ")
        return str(raw)

    def display_model(self) -> str:
        return self.model_name or self.model or "—"

    def display_year(self) -> str:
        y = self.model_year or self.year or self.manufacture_year
        return str(y) if y else "—"


class VehiclesPageResponse(BaseModel):
    content: list[VehicleItem] = Field(default_factory=list)
    total_elements: int = Field(default=0, alias="totalElements")
    total_pages: int = Field(default=0, alias="totalPages")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @classmethod
    def from_api_json(cls, data: Any) -> "VehiclesPageResponse":
        if isinstance(data, list):
            return cls(content=[VehicleItem.model_validate(v) for v in data])
        if isinstance(data, dict) and "content" in data:
            return cls.model_validate(data)
        return cls()
