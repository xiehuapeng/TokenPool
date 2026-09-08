import asyncio

import httpx
import pytest

from app.providers.deepseek import DeepSeekProvider
from app.providers.glm import GLMProvider
from app.providers.kimi import KimiProvider
from app.providers.qwen import QwenProvider
from app.utils.errors import GatewayError


PROVIDERS = [GLMProvider, DeepSeekProvider, KimiProvider, QwenProvider]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_class", PROVIDERS)
@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ReadError])
async def test_error_body_read_failure_closes_all_resources(
    provider_class, failure, monkeypatch
):
    class BrokenBody(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'{"error":'
            raise failure("test error body read failure")

        async def aclose(self):
            self.closed = True

    body = BrokenBody()
    response = httpx.Response(503, stream=body)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
    provider = provider_class()
    monkeypatch.setattr(provider, "_client", lambda _: client)
    with pytest.raises(GatewayError) as caught:
        await provider.open_chat_stream(
            {"messages": [{"role": "user", "content": "test"}]},
            upstream_model="test", timeout_seconds=1,
        )
    assert caught.value.code == (
        "upstream_timeout" if failure is httpx.ReadTimeout else "upstream_connection_error"
    )
    assert client.is_closed
    assert response.is_closed
    assert body.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_class", PROVIDERS)
async def test_error_body_cancel_still_closes_after_repeated_cancel(
    provider_class, monkeypatch
):
    reading = asyncio.Event()
    closing = asyncio.Event()
    release_close = asyncio.Event()
    closed = asyncio.Event()

    class WaitingBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            reading.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            closing.set()
            await release_close.wait()
            closed.set()

    response = httpx.Response(503, stream=WaitingBody())
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
    provider = provider_class()
    monkeypatch.setattr(provider, "_client", lambda _: client)
    task = asyncio.create_task(provider.open_chat_stream(
        {"messages": [{"role": "user", "content": "test"}]},
        upstream_model="test", timeout_seconds=1,
    ))
    await asyncio.wait_for(reading.wait(), timeout=1)
    task.cancel()
    await asyncio.wait_for(closing.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release_close.set()
    await asyncio.wait_for(closed.wait(), timeout=1)
    # Closing the response precedes closing the client in the cleanup task.
    for _ in range(10):
        if client.is_closed:
            break
        await asyncio.sleep(0)
    assert client.is_closed
    assert response.is_closed
