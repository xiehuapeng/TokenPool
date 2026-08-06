import httpx

from app.config.settings import get_settings
from app.providers.openai_compatible import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    code = "qwen"
    provider_name = "Qwen"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport=transport)

    def api_key(self) -> str:
        return get_settings().qwen_api_key.get_secret_value()

    def base_url(self) -> str:
        return get_settings().qwen_base_url
