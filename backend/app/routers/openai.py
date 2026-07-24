import asyncio
import json
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
from app.services.model_router import list_permitted_models, resolve_model
from app.services.usage_service import (
    create_usage_log,
    finish_usage_log,
    now_utc,
)
from app.utils.async_cleanup import run_cancellation_safe_cleanup
from app.utils.errors import GatewayError


router = APIRouter(prefix="/v1", tags=["openai"])


@router.get("/models", response_model=OpenAIModelList)
async def models(
    principal: Annotated[ApiPrincipal, Depends(api_principal)], session: DbSession
) -> OpenAIModelList:
    permitted = await list_permitted_models(session, user_id=principal.user.id)
    return OpenAIModelList(data=[OpenAIModel(id=item.public_model) for item in permitted])


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    response: Response,
    principal: Annotated[ApiPrincipal, Depends(api_principal)],
    session: DbSession,
):
    route = await resolve_model(
        session, user_id=principal.user.id, public_model=body.model
    )
    request_id = f"req_{uuid.uuid4().hex}"
    payload = body.model_dump(exclude_none=True)
    started = await create_usage_log(
        request_id=request_id,
        user_id=principal.user.id,
        api_key_id=principal.api_key.id,
        model=body.model,
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
            )
            exc.headers["X-Request-ID"] = request_id
            raise

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
        )
        exc.headers["X-Request-ID"] = request_id
        raise

    async def event_stream() -> AsyncIterator[bytes]:
        usage: dict | None = None
        first_token: datetime | None = None
        completed = False
        failure: Exception | None = None
        try:
            async for event in upstream.events():
                if event.comment:
                    yield f"{event.comment}\n\n".encode()
                    continue
                if event.done:
                    completed = True
                    yield b"data: [DONE]\n\n"
                    break
                if event.data is None:
                    continue
                if first_token is None and event.data.get("choices"):
                    first_token = now_utc()
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
                try:
                    await upstream.close()
                finally:
                    await finish_usage_log(
                        request_id,
                        started,
                        status=(
                            "success"
                            if completed
                            else "failed"
                            if failure
                            else "client_disconnected"
                        ),
                        http_status=upstream.http_status,
                        usage=usage,
                        first_token_time=first_token,
                        error_code="stream_interrupted" if failure else None,
                        error_message=str(failure) if failure else None,
                        upstream_request_id=upstream.upstream_request_id,
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
