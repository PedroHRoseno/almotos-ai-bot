from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = "0.0.0.0"
    # Railway injeta PORT; pydantic-settings lê PORT (case insensitive)
    port: int = 8000
    debug: bool = False
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    vehicles_api_url: str = "https://api.almotoscaruaru.com.br/api/public/vehicles"
    vehicles_api_token: str = ""
    vehicles_api_page_size: int = 50

    @property
    def whatsapp_graph_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.whatsapp_api_version}"
            f"/{self.whatsapp_phone_number_id}/messages"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
