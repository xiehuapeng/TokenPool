import json

import httpx
import pytest

from app.providers.deepseek import DeepSeekProvider
from app.utils.errors import GatewayError


@pytest.mark.asyncio
async def test_deepseek_provider_success():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        body = json.loads(request.content)
        assert body["model"] == "upstream-model"
        return httpx.Response(
            200,
            headers={"x-request-id": "provider-success"},
            json={
                "id": "chatcmpl-provider",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
        )

    provider = DeepSeekProvider(transport=httpx.MockTransport(handler))
    result = await provider.chat_completion(
        {"messages": [{"role": "user", "content": "test"}]},
        upstream_model="upstream-model",
        timeout_seconds=30,
    )
    assert result.data["usage"]["total_tokens"] == 6
    assert result.upstream_request_id == "provider-success"


@pytest.mark.asyncio
async def test_deepseek_provider_error_is_normalized_and_redacted():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "quota exceeded for sk-sensitive-example-token"
                }
            },
        )

    provider = DeepSeekProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(GatewayError) as caught:
        await provider.chat_completion(
            {"messages": [{"role": "user", "content": "test"}]},
            upstream_model="upstream-model",
            timeout_seconds=30,
        )
    assert caught.value.status_code == 429
    assert caught.value.code == "deepseek_upstream_error"
    assert "sensitive-example-token" not in caught.value.message

