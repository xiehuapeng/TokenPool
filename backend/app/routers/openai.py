import asyncio
from contextlib import suppress
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.dependencies import DbSession, api_principal
from app.providers.base import StreamEvent
from app.schemas.openai import (
    ChatCompletionRequest,
    OpenAIModel,
    OpenAIModelList,
)
from app.services.auth_service import ApiPrincipal
from app.services.cache_billing import request_cache_context
from app.services.model_router import (
    GATEWAY_MODEL_ID,
    ensure_reasoning_content,
    find_vision_fallback,
    list_permitted_models,
    model_requires_reasoning_content,
    model_supports_vision,
    payload_contains_images,
    resolve_requested_model,
)
from app.services.usage_service import (
    create_usage_log,
    finish_usage_log,
    mark_upstream_opened,
)
from app.utils.time import utc_now
from app.utils.async_cleanup import run_cancellation_safe_cleanup
from app.utils.errors import GatewayError
from app.utils.redaction import redact_secrets


router = APIRouter(prefix="/v1", tags=["openai"])
logger = logging.getLogger("tokenpool.stream")
STREAM_HEARTBEAT_SECONDS = 15.0


async def events_with_heartbeat(
    events: AsyncIterator[StreamEvent], interval_seconds: float = STREAM_HEARTBEAT_SECONDS
) -> AsyncIterator[StreamEvent]:
    """Keep an established SSE connection active while the provider is silent.

    The pending upstream read is not cancelled on each heartbeat. This does
    not cover the pre-header wait in open_chat_stream.
    """
    iterator = events.__aiter__()
    pending: asyncio.Task[StreamEvent] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=interval_seconds)
            if not done:
                yield StreamEvent(comment=": keep-alive")
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                pending = None
                return
            pending = None
            yield event
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()


@router.get("/models", response_model=OpenAIModelList)
async def models(
    principal: Annotated[ApiPrincipal, Depends(api_principal)], session: DbSession
) -> OpenAIModelList:
    permitted = await list_permitted_models(session, user_id=principal.user.id)
    return OpenAIModelList(
        data=[OpenAIModel(id=GATEWAY_MODEL_ID)] if permitted else []
    )


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    response: Response,
    principal: Annotated[ApiPrincipal, Depends(api_principal)],
    session: DbSession,
):
    route = await resolve_requested_model(
        session,
        user_id=principal.user.id,
        requested_model=body.model,
        key_preferred_model_id=principal.api_key.preferred_model_id,
    )
    request_id = f"req_{uuid.uuid4().hex}"
    payload = body.model_dump(exclude_none=True)
    original_model = route.model.public_model
    route_reason = "preference" if body.model == GATEWAY_MODEL_ID else "explicit"
    if payload_contains_images(payload) and not model_supports_vision(route.model):
        if body.model != GATEWAY_MODEL_ID:
            raise GatewayError(
                "当前请求或历史消息包含图片，但指定模型不支持视觉理解。"
                "请显式选择支持视觉的模型，或使用 team-coding 允许自动切换；"
                "如需继续使用当前模型，请移除图片上下文或新建纯文本会话。",
                status_code=400,
                code="vision_not_supported",
                param="model",
                headers={"X-Request-ID": request_id},
            )
        fallback = await find_vision_fallback(
            session,
            user_id=principal.user.id,
            exclude_model_id=route.model.id,
        )
        if fallback is None:
            raise GatewayError(
                "当前请求包含图片，但目标模型不支持视觉理解，"
                "请在工作台切换到支持视觉的模型或联系管理员启用",
                status_code=400,
                code="vision_not_supported",
                param="model",
                headers={"X-Request-ID": request_id},
            )
        route = fallback
        route_reason = "vision_fallback"
    if model_requires_reasoning_content(route.model):
        payload = ensure_reasoning_content(payload)
    started = await create_usage_log(
        request_id=request_id,
        user_id=principal.user.id,
        api_key_id=principal.api_key.id,
        requested_model=body.model,
        model=route.model.public_model,
        provider=route.provider_config.code,
        upstream_model=route.model.upstream_model,
        stream=body.stream,
        original_model=original_model,
        route_reason=route_reason,
        cache_context=request_cache_context(route.provider_config.code, payload),
    )
    route_headers = {
        "X-Request-ID": request_id,
        "X-Original-Model": original_model,
        "X-Actual-Model": route.model.public_model,
        "X-Route-Reason": route_reason,
    }

    if not body.stream:
        try:
            result = await route.provider.chat_completion(
                payload,
                upstream_model=route.model.upstream_model,
                timeout_seconds=route.provider_config.timeout_seconds,
            )
            result.data["model"] = body.model
            await finish_usage_log(
                request_id,
                started,
                status="success",
                http_status=result.http_status,
                usage=result.data.get("usage"),
                upstream_request_id=result.upstream_request_id,
                model_config_id=route.model.id,
            )
            response.headers.update(route_headers)
            return result.data
        except GatewayError as exc:
            await finish_usage_log(
                request_id,
                started,
                status="failed",
                http_status=exc.status_code,
                error_code=exc.code,
                error_message=exc.message,
                model_config_id=route.model.id,
            )
            exc.headers["X-Request-ID"] = request_id
            raise

    upstream_open_started = time.monotonic()
    try:
        upstream = await route.provider.open_chat_stream(
            payload,
            upstream_model=route.model.upstream_model,
            timeout_seconds=route.provider_config.timeout_seconds,
        )
    except asyncio.CancelledError:
        await run_cancellation_safe_cleanup(
            finish_usage_log(
                request_id,
                started,
                status="client_disconnected",
                http_status=None,
                model_config_id=route.model.id,
                stream_observation={"phase": "opening", "usage_seen": False, "done_seen": False},
            )
        )
        raise
    except GatewayError as exc:
        await run_cancellation_safe_cleanup(
            finish_usage_log(
                request_id,
                started,
                status="failed",
                http_status=exc.status_code,
                error_code=exc.code,
                error_message=exc.message,
                model_config_id=route.model.id,
                stream_observation={"phase": "opening", "usage_seen": False, "done_seen": False},
            )
        )
        exc.headers["X-Request-ID"] = request_id
        raise
    upstream_open_ms = round((time.monotonic() - upstream_open_started) * 1000)
    try:
        await mark_upstream_opened(
            request_id,
            http_status=upstream.http_status,
            upstream_request_id=upstream.upstream_request_id,
        )
    except (asyncio.CancelledError, Exception) as exc:
        client_cancelled = isinstance(exc, asyncio.CancelledError)

        async def cleanup_opened_stream() -> None:
            try:
                await upstream.close()
            finally:
                await finish_usage_log(
                    request_id,
                    started,
                    status="client_disconnected" if client_cancelled else "failed",
                    http_status=upstream.http_status,
                    error_code=None if client_cancelled else "upstream_open_audit_failed",
                    upstream_request_id=upstream.upstream_request_id,
                    model_config_id=route.model.id,
                    stream_observation={
                        "phase": "opening",
                        "upstream_open_ms": upstream_open_ms,
                        "usage_seen": False,
                        "done_seen": False,
                    },
                )

        await run_cancellation_safe_cleanup(cleanup_opened_stream())
        raise

    async def event_stream() -> AsyncIterator[bytes]:
        usage: dict | None = None
        first_token: datetime | None = None
        completed = False
        failure: Exception | None = None
        failure_code: str | None = None
        first_event_ms: int | None = None
        first_choices_ms: int | None = None
        first_content_ms: int | None = None
        first_reasoning_ms: int | None = None
        previous_event_at: float | None = None
        max_event_gap_ms = 0
        event_count = 0
        data_event_count = 0
        content_chunk_count = 0
        reasoning_chunk_count = 0
        finish_reason_seen = False
        provider_response_id: str | None = None
        try:
            async for event in events_with_heartbeat(upstream.events()):
                event_at = time.monotonic()
                event_count += 1
                elapsed_ms = round((event_at - upstream_open_started) * 1000)
                if first_event_ms is None:
                    first_event_ms = elapsed_ms
                if previous_event_at is not None:
                    max_event_gap_ms = max(
                        max_event_gap_ms,
                        round((event_at - previous_event_at) * 1000),
                    )
                previous_event_at = event_at
                if event.comment:
                    yield f"{event.comment}\n\n".encode()
                    continue
                if event.done:
                    completed = True
                    yield b"data: [DONE]\n\n"
                    break
                if event.data is None:
                    continue
                data_event_count += 1
                event_response_id = event.data.get("id")
                if (
                    provider_response_id is None
                    and isinstance(event_response_id, str)
                    and 0 < len(event_response_id) <= 160
                ):
                    provider_response_id = event_response_id
                if event.data.get("error") is not None:
                    upstream_error = event.data["error"]
                    message = (
                        upstream_error.get("message")
                        if isinstance(upstream_error, dict)
                        else None
                    )
                    raise GatewayError(
                        redact_secrets(message)[:500]
                        if message
                        else "Upstream reported a stream error",
                        status_code=502,
                        error_type="upstream_error",
                        code="upstream_stream_error",
                    )
                choices = event.data.get("choices")
                if choices:
                    if first_token is None:
                        first_token = utc_now()
                        first_choices_ms = elapsed_ms
                    for choice in choices:
                        if not isinstance(choice, dict):
                            continue
                        if choice.get("finish_reason") is not None:
                            finish_reason_seen = True
                        delta = choice.get("delta")
                        if not isinstance(delta, dict):
                            continue
                        if isinstance(delta.get("content"), str) and delta["content"]:
                            content_chunk_count += 1
                            if first_content_ms is None:
                                first_content_ms = elapsed_ms
                        if (
                            isinstance(delta.get("reasoning_content"), str)
                            and delta["reasoning_content"]
                        ):
                            reasoning_chunk_count += 1
                            if first_reasoning_ms is None:
                                first_reasoning_ms = elapsed_ms
                if event.data.get("usage"):
                    usage = event.data["usage"]
                event.data["model"] = body.model
                yield f"data: {json.dumps(event.data, ensure_ascii=False)}\n\n".encode(
                    "utf-8"
                )
            if not completed:
                raise GatewayError(
                    "Upstream stream ended before completion",
                    status_code=502,
                    error_type="upstream_error",
                    code="upstream_incomplete_stream",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = exc
            failure_code = (
                redact_secrets(exc.code)[:100]
                if isinstance(exc, GatewayError)
                else "stream_interrupted"
            )
            error = {
                "error": {
                    "message": (
                        exc.message[:500]
                        if isinstance(exc, GatewayError)
                        else "Upstream stream interrupted"
                    ),
                    "type": "upstream_error",
                    "code": failure_code,
                }
            }
            yield f"data: {json.dumps(error)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        finally:
            async def cleanup_stream() -> None:
                status = (
                    "failed"
                    if failure
                    else "success"
                    if completed
                    else "client_disconnected"
                )
                try:
                    await upstream.close()
                finally:
                    try:
                        await finish_usage_log(
                            request_id,
                            started,
                            status=status,
                            http_status=upstream.http_status,
                            usage=usage,
                            first_token_time=first_token,
                            error_code=failure_code,
                            error_message=str(failure) if failure else None,
                            upstream_request_id=upstream.upstream_request_id,
                            model_config_id=route.model.id,
                            stream_observation={
                                "phase": "streaming",
                                "upstream_open_ms": upstream_open_ms,
                                "first_event_ms": first_event_ms,
                                "first_choices_ms": first_choices_ms,
                                "first_reasoning_ms": first_reasoning_ms,
                                "first_content_ms": first_content_ms,
                                "max_event_gap_ms": max_event_gap_ms,
                                "event_count": event_count,
                                "data_event_count": data_event_count,
                                "reasoning_chunks": reasoning_chunk_count,
                                "content_chunks": content_chunk_count,
                                "finish_reason_seen": finish_reason_seen,
                                "usage_seen": usage is not None,
                                "done_seen": completed,
                                "provider_response_id": provider_response_id,
                            },
                        )
                    finally:
                        # Alembic configures logging during startup and disables
                        # loggers that are not declared in alembic.ini.
                        logger.disabled = False
                        logger.setLevel(logging.INFO)
                        logger.info(
                            "stream_observation request_id=%s provider=%s "
                            "model=%s upstream_open_ms=%s first_event_ms=%s "
                            "first_choices_ms=%s first_reasoning_ms=%s "
                            "first_content_ms=%s max_event_gap_ms=%s "
                            "events=%s data_events=%s reasoning_chunks=%s "
                            "content_chunks=%s status=%s provider_diagnostics=%s",
                            request_id,
                            route.provider_config.code,
                            route.model.public_model,
                            upstream_open_ms,
                            first_event_ms,
                            first_choices_ms,
                            first_reasoning_ms,
                            first_content_ms,
                            max_event_gap_ms,
                            event_count,
                            data_event_count,
                            reasoning_chunk_count,
                            content_chunk_count,
                            status,
                            getattr(upstream, "diagnostics", {}),
                        )

            await run_cancellation_safe_cleanup(
                cleanup_stream()
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            **route_headers,
        },
    )
