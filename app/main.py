import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.config import get_settings
from app.routes import create_api_router
from app.scheduler import start_wishlist_scheduler, stop_wishlist_scheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.almotos_ai_url:
        logging.getLogger(__name__).warning("ALMOTOS_AI_URL não configurada")
    if not settings.whatsapp_access_token:
        logging.getLogger(__name__).warning("WHATSAPP_ACCESS_TOKEN não configurada")
    if not settings.whatsapp_verify_token:
        logging.getLogger(__name__).warning(
            "WHATSAPP_VERIFY_TOKEN não configurada — verificação do webhook Meta vai falhar"
        )
    if not settings.whatsapp_app_secret:
        logging.getLogger(__name__).warning(
            "WHATSAPP_APP_SECRET não configurado — POST /webhook exige DEBUG=true em local"
        )
    if not settings.chatwoot_base_url or not settings.chatwoot_api_token:
        logging.getLogger(__name__).warning(
            "CHATWOOT_BASE_URL/CHATWOOT_API_TOKEN não configurados — POST /webhook/chatwoot não envia respostas"
        )
    if not settings.almotos_backend_url:
        logging.getLogger(__name__).warning(
            "ALMOTOS_BACKEND_URL não configurada — job da lista de espera não consulta o SoR"
        )
    start_wishlist_scheduler(settings)
    yield
    stop_wishlist_scheduler()


app = FastAPI(
    title="AlMotos AI Bot",
    description="Adapter Chatwoot (WhatsApp / Meta Cloud API) do agent runtime almotos-ai",
    version="1.3.0",
    lifespan=lifespan,
)

app.include_router(create_api_router())


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
