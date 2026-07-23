from app.providers.base import BaseProvider


class GLMProvider(BaseProvider):
    code = "glm"

    async def chat_completion(self, payload, *, upstream_model, timeout_seconds):
        raise NotImplementedError

    async def open_chat_stream(self, payload, *, upstream_model, timeout_seconds):
        raise NotImplementedError

