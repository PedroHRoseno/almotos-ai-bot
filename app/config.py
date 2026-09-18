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
    port: int = 8000
    debug: bool = False
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    whatsapp_app_secret: str = ""

    almotos_ai_url: str = "http://localhost:3100"
    almotos_backend_url: str = "http://localhost:8080"
    internal_api_key: str = ""

    chatwoot_base_url: str = ""
    chatwoot_api_token: str = ""
    chatwoot_account_id: int = 1

    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""
    # Token extra aceito no webhook inbound (costuma ser o token da instância,
    # diferente da AUTHENTICATION_API_KEY global usada em EVOLUTION_API_KEY).
    evolution_webhook_secret: str = ""
    # false (padrão): loga mismatch e processa — necessário para e2e enquanto a
    # Evolution manda instance token no body e global key no header. true = 401.
    evolution_webhook_auth_required: bool = False
    # Janela para juntar mensagens rápidas do mesmo conversation_id antes da IA.
    chatwoot_debounce_seconds: float = 4.0
    # Polling da lista de espera (template Meta). 1 min para testar em produção.
    wishlist_poll_interval_minutes: int = 1

    @property
    def whatsapp_graph_url(self) -> str:
        return (
            f"https://graph.facebook.com/{self.whatsapp_api_version}"
            f"/{self.whatsapp_phone_number_id}/messages"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
