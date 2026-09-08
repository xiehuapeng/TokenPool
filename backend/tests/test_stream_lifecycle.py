import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from app.providers.base import StreamEvent
from app.routers import openai as router
from app.schemas.openai import ChatCompletionRequest
from app.utils.errors import GatewayError
from app.utils.time import utc_now


class ScriptedStream:
    http_status = 200
    upstream_request_id = "test-upstream"

    def __init__(self, events):
        self.script = events
        self.closed = False

    async def events(self):
        for event in self.script:
            yield event

    async def close(self):
        self.closed = True


@pytest.fixture
def stream_harness(monkeypatch):
    terminal = []
    observations = []

    async def finish(*_args, **kwargs):
        terminal.append(kwargs)

    monkeypatch.setattr(router, "finish_usage_log", finish)
    monkeypatch.setattr(router, "create_usage_log", AsyncMock(return_value=utc_now()))
    monkeypatch.setattr(
        router.logger, "info", lambda template, *args: observations.append(template % args)
    )

    async def response_for(stream=None, *, open_stream=None):
        provider = SimpleNamespace(
            open_chat_stream=open_stream or AsyncMock(return_value=stream)
        )
        route = SimpleNamespace(
            provider=provider,
            model=SimpleNamespace(
                id=1, public_model="test-model", upstream_model="test-model",
                capabilities={},
            ),
            provider_config=SimpleNamespace(code="test", timeout_seconds=1),
        )
        monkeypatch.setattr(
            router, "resolve_requested_model", AsyncMock(return_value=route)
        )
        return await router.chat_completions(
            ChatCompletionRequest(
                model="team-coding", messages=[{"role": "user", "content": "test"}],
                stream=True,
            ),
            Response(),
            SimpleNamespace(
                user=SimpleNamespace(id=1),
                api_key=SimpleNamespace(id=1, preferred_model_id=None),
            ),
            None,
        )

    return response_for, terminal, observations


async def consume(response):
    return b"".join([chunk async for chunk in response.body_iterator]).decode()


@pytest.mark.asyncio
async def test_stream_error_is_failed_redacted_and_bounded(stream_harness):
    response_for, terminal, _ = stream_harness
    secret = "sk-team-" + "sensitive" * 8
    stream = ScriptedStream([
        StreamEvent(data={"error": {"message": f"Bearer {secret} " + "x" * 700,
                                    "code": secret, "extra": secret}}),
        StreamEvent(done=True),
    ])
    text = await consume(await response_for(stream))
    error = json.loads(text.splitlines()[0][6:])["error"]
    assert error["code"] == "upstream_stream_error"
    assert len(error["message"]) <= 500
    assert secret not in text
    assert text.count("data: [DONE]") == 1
    assert terminal[0]["status"] == "failed"
    assert terminal[0]["error_code"] == "upstream_stream_error"
    assert secret not in terminal[0]["error_message"]
    assert stream.closed


@pytest.mark.asyncio
async def test_upstream_eof_without_done_is_not_client_disconnect(stream_harness):
    response_for, terminal, _ = stream_harness
    stream = ScriptedStream([
        StreamEvent(data={"choices": [{"delta": {"content": "partial"}}]}),
    ])
    text = await consume(await response_for(stream))
    assert "partial" in text
    assert "upstream_incomplete_stream" in text
    assert text.endswith("data: [DONE]\n\n")
    assert terminal[0]["status"] == "failed"
    assert terminal[0]["error_code"] == "upstream_incomplete_stream"
    assert stream.closed


@pytest.mark.asyncio
async def test_first_content_ignores_empty_chunks_and_preserves_payloads(
    stream_harness, monkeypatch
):
    response_for, terminal, observations = stream_harness
    clock = iter([10, 10, 10.1, 10.2, 11, 13, 14, 15])
    monkeypatch.setattr(
        router, "time", SimpleNamespace(monotonic=lambda: next(clock))
    )
    tool_calls = [{"index": 0, "id": "call_test", "type": "function",
                   "function": {"name": "test", "arguments": "{}"}}]
    usage = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    stream = ScriptedStream([
        StreamEvent(data={"choices": [{"delta": {"role": "assistant", "content": ""}}]}),
        StreamEvent(data={"choices": [{"delta": {"reasoning_content": "", "tool_calls": tool_calls}}]}),
        StreamEvent(data={"choices": [{"delta": {"reasoning_content": "reason", "content": ""}}]}),
        StreamEvent(data={"choices": [{"delta": {"content": "answer"}}]}),
        StreamEvent(data={"choices": [], "usage": usage}),
        StreamEvent(done=True),
    ])
    text = await consume(await response_for(stream))
    chunks = [json.loads(line[6:]) for line in text.splitlines()
              if line.startswith("data: {")]
    assert chunks[1]["choices"][0]["delta"]["tool_calls"] == tool_calls
    assert chunks[2]["choices"][0]["delta"]["reasoning_content"] == "reason"
    assert chunks[-1]["usage"] == usage
    assert all(chunk["model"] == "team-coding" for chunk in chunks)
    assert terminal[0]["status"] == "success"
    assert terminal[0]["usage"] == usage
    observation = observations[0]
    for expected in ("first_choices_ms=100", "first_reasoning_ms=1000",
                     "first_content_ms=3000", "reasoning_chunks=1", "content_chunks=1"):
        assert expected in observation
    assert stream.closed


@pytest.mark.asyncio
async def test_real_client_cancel_stays_client_disconnected(stream_harness):
    response_for, terminal, _ = stream_harness
    started = asyncio.Event()

    class WaitingStream(ScriptedStream):
        async def events(self):
            started.set()
            await asyncio.Event().wait()
            yield StreamEvent(done=True)

    stream = WaitingStream([])
    task = asyncio.create_task(consume(await response_for(stream)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert terminal[0]["status"] == "client_disconnected"
    assert terminal[0]["error_code"] is None
    assert stream.closed


@pytest.mark.asyncio
async def test_open_stream_failure_finishes_audit(stream_harness):
    response_for, terminal, _ = stream_harness
    error = GatewayError("Timed out", status_code=504, code="upstream_timeout")
    with pytest.raises(GatewayError):
        await response_for(open_stream=AsyncMock(side_effect=error))
    assert terminal[0]["status"] == "failed"
    assert terminal[0]["http_status"] == 504
    assert terminal[0]["error_code"] == "upstream_timeout"


@pytest.mark.asyncio
async def test_open_stream_cancel_finishes_audit(stream_harness):
    response_for, terminal, _ = stream_harness
    with pytest.raises(asyncio.CancelledError):
        await response_for(open_stream=AsyncMock(side_effect=asyncio.CancelledError))
    assert terminal[0]["status"] == "client_disconnected"
