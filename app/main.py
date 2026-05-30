import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.config import get_settings
from app.routes import create_api_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.openai_api_key:
        logging.getLogger(__name__).warning("OPENAI_API_KEY não configurada")
    if not settings.whatsapp_access_token:
        logging.getLogger(__name__).warning("WHATSAPP_ACCESS_TOKEN não configurada")
    if not settings.whatsapp_verify_token:
        logging.getLogger(__name__).warning(
            "WHATSAPP_VERIFY_TOKEN não configurada — verificação do webhook Meta vai falhar"
        )
    if not settings.seller_1_phone or not settings.seller_2_phone:
        logging.getLogger(__name__).warning(
            "SELLER_1_PHONE ou SELLER_2_PHONE não configurados — links de handoff ficarão incompletos"
        )
    elif settings.whatsapp_verify_token.strip() != settings.whatsapp_verify_token:
        logging.getLogger(__name__).warning(
            "WHATSAPP_VERIFY_TOKEN tem espaços no início/fim — remova no Railway"
        )
    yield


app = FastAPI(
    title="AlMotos AI Bot",
    description="Chatbot WhatsApp integrado à OpenAI e à API de veículos AlMotos",
    version="1.0.0",
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
