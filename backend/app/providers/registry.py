from app.providers.base import BaseProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.glm import GLMProvider
from app.utils.errors import GatewayError


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {
            "deepseek": DeepSeekProvider(),
            "glm": GLMProvider(),
        }

    def get(self, code: str) -> BaseProvider:
        provider = self._providers.get(code)
        if provider is None:
            raise GatewayError(
                f"Provider {code} 尚未实现",
                status_code=503,
                error_type="provider_error",
                code="provider_not_implemented",
            )
        return provider


provider_registry = ProviderRegistry()
