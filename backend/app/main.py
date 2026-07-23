from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.database.session import engine
from app.routers import admin, auth, health, me, openai
from app.services.bootstrap import seed_initial_data
from app.utils.errors import GatewayError, gateway_error_handler
from app.utils.redaction import configure_secret_redaction


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    from app.database.migrations import upgrade_database

    if settings.auto_migrate:
        await upgrade_database()
    await seed_initial_data()
    try:
        yield
    finally:
        await engine.dispose()


settings = get_settings()
configure_secret_redaction()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(GatewayError, gateway_error_handler)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(openai.router)
