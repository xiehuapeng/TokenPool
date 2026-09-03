import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.dependencies import DbSession, api_principal
from app.schemas.openai import (
    ChatCompletionRequest,
    OpenAIModel,
    OpenAIModelList,
)
from app.services.auth_service import ApiPrincipal
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
)
from app.utils.time import utc_now
from app.utils.async_cleanup import run_cancellation_safe_cleanup
from app.utils.errors import GatewayError


router = APIRouter(prefix="/v1", tags=["openai"])
logger = logging.getLogger("tokenpool.stream")


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
    if payload_contains_images(payload) and not model_supports_vision(route.model):
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
            )
        route = fallback
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
    )

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
            response.headers["X-Request-ID"] = request_id
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
    upstream_open_ms = round((time.monotonic() - upstream_open_started) * 1000)

    async def event_stream() -> AsyncIterator[bytes]:
        usage: dict | None = None
        first_token: datetime | None = None
        completed = False
        failure: Exception | None = None
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
        try:
            async for event in upstream.events():
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
                choices = event.data.get("choices")
                if choices:
                    if first_token is None:
                        first_token = utc_now()
                        first_choices_ms = elapsed_ms
                    for choice in choices:
                        if not isinstance(choice, dict):
                            continue
                        delta = choice.get("delta")
                        if not isinstance(delta, dict):
                            continue
                        if delta.get("content") is not None:
                            content_chunk_count += 1
                            if first_content_ms is None:
                                first_content_ms = elapsed_ms
                        if delta.get("reasoning_content") is not None:
                            reasoning_chunk_count += 1
                            if first_reasoning_ms is None:
                                first_reasoning_ms = elapsed_ms
                if event.data.get("usage"):
                    usage = event.data["usage"]
                event.data["model"] = body.model
                yield f"data: {json.dumps(event.data, ensure_ascii=False)}\n\n".encode(
                    "utf-8"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = exc
            error = {
                "error": {
                    "message": "Upstream stream interrupted",
                    "type": "upstream_error",
                    "code": "stream_interrupted",
                }
            }
            yield f"data: {json.dumps(error)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        finally:
            async def cleanup_stream() -> None:
                status = (
                    "success"
                    if completed
                    else "failed"
                    if failure
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
                            error_code="stream_interrupted" if failure else None,
                            error_message=str(failure) if failure else None,
                            upstream_request_id=upstream.upstream_request_id,
                            model_config_id=route.model.id,
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
            "X-Request-ID": request_id,
        },
    )
