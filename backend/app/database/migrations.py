import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config.settings import get_settings


BACKEND_DIR = Path(__file__).resolve().parents[2]


def _upgrade_sync() -> None:
    settings = get_settings()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option(
        "script_location", str(BACKEND_DIR / "migrations").replace("\\", "/")
    )
    config.set_main_option(
        "sqlalchemy.url", settings.database_url.replace("%", "%%")
    )
    command.upgrade(config, "head")


async def upgrade_database() -> None:
    await asyncio.to_thread(_upgrade_sync)

