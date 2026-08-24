import json

import httpx
import pytest

from app.providers.kimi import KimiProvider
from app.providers.qwen import QwenProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_class", "model_id"),
    [
        (KimiProvider, "kimi-k2.7-code"),
        (QwenProvider, "qwen3-coder-plus"),
    ],
)
async def test_provider_lists_models_without_chat_request(
    provider_class, model_id
):
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": model_id,
                        "object": "model",
                        "ownedBy": "system",
                    }
                ],
            },
        )

    provider = provider_class(transport=httpx.MockTransport(handler))
    models = await provider.list_models(timeout_seconds=30)

    assert [item.id for item in models] == [model_id]
    assert models[0].owned_by == "system"
    assert requests == [("GET", requests[0][1])]
    assert requests[0][1].endswith("/models")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_class", "model_id"),
    [
        (KimiProvider, "kimi-k2.7-code"),
        (QwenProvider, "qwen3-coder-plus"),
    ],
)
async def test_provider_chat_completion(provider_class, model_id):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert body["model"] == model_id
        return httpx.Response(
            200,
            headers={"x-request-id": "compatible-request"},
            json={
                "id": "chatcmpl-compatible",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            },
        )

    provider = provider_class(transport=httpx.MockTransport(handler))
    result = await provider.chat_completion(
        {"messages": [{"role": "user", "content": "test"}]},
        upstream_model=model_id,
        timeout_seconds=30,
    )

    assert result.data["usage"]["total_tokens"] == 3
    assert result.upstream_request_id == "compatible-request"
