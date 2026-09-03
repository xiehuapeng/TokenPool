import json

import httpx
import pytest

from app.providers.glm import GLMProvider
from app.utils.errors import GatewayError


@pytest.mark.asyncio
async def test_glm_provider_lists_upstream_models():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "glm-4.5-air", "owned_by": "zhipu"},
                    {"id": "glm-5", "owned_by": "zhipu"},
                ],
            },
        )

    provider = GLMProvider(transport=httpx.MockTransport(handler))
    models = await provider.list_models(timeout_seconds=30)

    assert [item.id for item in models] == ["glm-4.5-air", "glm-5"]
    assert models[0].owned_by == "zhipu"


@pytest.mark.asyncio
async def test_glm_provider_non_stream_success():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "glm-4.5-air"
        assert body["stream"] is False
        return httpx.Response(
            200,
            headers={"x-request-id": "glm-request-1"},
            json={
                "id": "chatcmpl-glm",
                "model": "glm-4.5-air",
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

    provider = GLMProvider(transport=httpx.MockTransport(handler))
    result = await provider.chat_completion(
        {"messages": [{"role": "user", "content": "test"}]},
        upstream_model="glm-4.5-air",
        timeout_seconds=30,
    )

    assert result.data["usage"]["total_tokens"] == 6
    assert result.upstream_request_id == "glm-request-1"


@pytest.mark.asyncio
async def test_glm_provider_stream_includes_usage_and_parses_sse():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["stream_options"]["include_usage"] is True
        return httpx.Response(
            200,
            headers={"x-log-id": "glm-stream-1"},
            content=(
                'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":2,'
                '"completion_tokens":1,"total_tokens":3}}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    provider = GLMProvider(transport=httpx.MockTransport(handler))
    stream = await provider.open_chat_stream(
        {"messages": [{"role": "user", "content": "test"}]},
        upstream_model="glm-4.5-air",
        timeout_seconds=30,
    )
    events = [event async for event in stream.events()]
    await stream.close()

    assert events[0].data["choices"][0]["delta"]["content"] == "ok"
    assert events[1].data["usage"]["total_tokens"] == 3
    assert events[2].done is True
    assert stream.upstream_request_id == "glm-stream-1"


@pytest.mark.asyncio
async def test_glm_provider_stream_filters_trae_incompatible_sse_events():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                'event: progress_notice\n'
                'id: 1\n'
                'data: "Processing_1"\n\n'
                'event: context_usage\n'
                'data: {"tokens":123}\n\n'
                'data: "unexpected scalar"\n\n'
                'data: not-json\n\n'
                ': keep-alive\n\n'
                'data: {"choices":[{"delta":{"reasoning_content":"r"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                'data: {"choices":[],"usage":{"total_tokens":3}}\n\n'
                'data: [DONE]\n\n'
            ),
        )

    provider = GLMProvider(transport=httpx.MockTransport(handler))
    stream = await provider.open_chat_stream(
        {"messages": [{"role": "user", "content": "test"}]},
        upstream_model="glm-5.3-flash",
        timeout_seconds=30,
    )
    events = [event async for event in stream.events()]
    await stream.close()

    assert [event.comment for event in events if event.comment] == [": keep-alive"]
    data_events = [event.data for event in events if event.data is not None]
    assert data_events[0]["choices"][0]["delta"]["reasoning_content"] == "r"
    assert data_events[1]["choices"][0]["delta"]["content"] == "ok"
    assert data_events[2]["usage"]["total_tokens"] == 3
    assert events[-1].done is True
    assert stream.diagnostics == {
        "ignored_sse_events": {"context_usage": 1, "progress_notice": 1},
        "invalid_json_events": 1,
        "non_object_data_events": 1,
    }


@pytest.mark.asyncio
async def test_glm_provider_error_is_normalized_and_redacted():
    leaked_key = "a" * 32 + ".sensitiveTokenPart"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": f"quota exceeded for {leaked_key}"}},
        )

    provider = GLMProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(GatewayError) as caught:
        await provider.chat_completion(
            {"messages": [{"role": "user", "content": "test"}]},
            upstream_model="glm-4.5-air",
            timeout_seconds=30,
        )

    assert caught.value.status_code == 429
    assert caught.value.code == "glm_upstream_error"
    assert "sensitiveTokenPart" not in caught.value.message
