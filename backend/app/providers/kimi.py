import httpx

from app.config.settings import get_settings
from app.providers.openai_compatible import OpenAICompatibleProvider


class KimiProvider(OpenAICompatibleProvider):
    code = "kimi"
    provider_name = "Kimi"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport=transport)

    def api_key(self) -> str:
        return get_settings().kimi_api_key.get_secret_value()

    def base_url(self) -> str:
        return get_settings().kimi_base_url
