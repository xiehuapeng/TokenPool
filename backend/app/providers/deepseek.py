import json
from typing import Any, AsyncIterator

import httpx

from app.config.settings import get_settings
from app.providers.base import (
    BaseProvider,
    ProviderModel,
    ProviderResult,
    ProviderStream,
    StreamEvent,
)
from app.utils.errors import GatewayError


def _upstream_error(response: httpx.Response, body: bytes) -> GatewayError:
    message = "Upstream provider request failed"
    try:
        parsed = json.loads(body)
        message = parsed.get("error", {}).get("message") or message
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    status_code = response.status_code
    if status_code < 400 or status_code > 599:
        status_code = 502
    return GatewayError(
        str(message)[:500],
        status_code=status_code,
        error_type="upstream_error",
        code="deepseek_upstream_error",
    )


class DeepSeekStream(ProviderStream):
    def __init__(self, client: httpx.AsyncClient, response: httpx.Response) -> None:
        self.client = client
        self.response = response
        self.http_status = response.status_code
        self.upstream_request_id = response.headers.get("x-request-id")

    async def events(self) -> AsyncIterator[StreamEvent]:
        async for line in self.response.aiter_lines():
            if not line:
                continue
            if line.startswith(":"):
                yield StreamEvent(comment=line)
                continue
            if not line.startswith("data:"):
                continue
            value = line[5:].strip()
            if value == "[DONE]":
                yield StreamEvent(done=True)
                return
            try:
                yield StreamEvent(data=json.loads(value))
            except json.JSONDecodeError:
                continue

    async def close(self) -> None:
        await self.response.aclose()
        await self.client.aclose()


class DeepSeekProvider(BaseProvider):
    code = "deepseek"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        api_key = get_settings().deepseek_api_key.get_secret_value()
        if not api_key:
            raise GatewayError(
                "DeepSeek Provider尚未配置",
                status_code=503,
                error_type="provider_error",
                code="provider_unconfigured",
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _url() -> str:
        return f"{get_settings().deepseek_base_url.rstrip('/')}/chat/completions"

    @staticmethod
    def _models_url() -> str:
        return f"{get_settings().deepseek_base_url.rstrip('/')}/models"

    @staticmethod
    def _timeout(seconds: int) -> httpx.Timeout:
        return httpx.Timeout(connect=10, read=seconds, write=30, pool=10)

    def _client(self, timeout_seconds: int) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout(timeout_seconds),
            transport=self._transport,
        )

    async def list_models(self, *, timeout_seconds: int) -> list[ProviderModel]:
        async with self._client(timeout_seconds) as client:
            try:
                response = await client.get(
                    self._models_url(), headers=self._headers()
                )
            except httpx.TimeoutException as exc:
                raise GatewayError(
                    "获取DeepSeek模型列表超时",
                    status_code=504,
                    error_type="upstream_error",
                    code="upstream_timeout",
                ) from exc
            except httpx.HTTPError as exc:
                raise GatewayError(
                    "无法连接DeepSeek模型列表接口",
                    status_code=502,
                    error_type="upstream_error",
                    code="upstream_connection_error",
                ) from exc
        if not response.is_success:
            raise _upstream_error(response, response.content)
        try:
            data = response.json().get("data", [])
            return [
                ProviderModel(id=item["id"], owned_by=item.get("owned_by"))
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
        except (AttributeError, TypeError, json.JSONDecodeError) as exc:
            raise GatewayError(
                "DeepSeek返回了无效的模型列表",
                status_code=502,
                error_type="upstream_error",
                code="invalid_upstream_response",
            ) from exc

    async def chat_completion(
        self, payload: dict[str, Any], *, upstream_model: str, timeout_seconds: int
    ) -> ProviderResult:
        upstream_payload = {**payload, "model": upstream_model, "stream": False}
        async with self._client(timeout_seconds) as client:
            try:
                response = await client.post(
                    self._url(), headers=self._headers(), json=upstream_payload
                )
            except httpx.TimeoutException as exc:
                raise GatewayError(
                    "DeepSeek请求超时",
                    status_code=504,
                    error_type="upstream_error",
                    code="upstream_timeout",
                ) from exc
            except httpx.HTTPError as exc:
                raise GatewayError(
                    "无法连接DeepSeek",
                    status_code=502,
                    error_type="upstream_error",
                    code="upstream_connection_error",
                ) from exc
        if not response.is_success:
            raise _upstream_error(response, response.content)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise GatewayError(
                "DeepSeek返回了无效JSON",
                status_code=502,
                error_type="upstream_error",
                code="invalid_upstream_response",
            ) from exc
        return ProviderResult(
            data=data,
            http_status=response.status_code,
            upstream_request_id=response.headers.get("x-request-id"),
        )

    async def open_chat_stream(
        self, payload: dict[str, Any], *, upstream_model: str, timeout_seconds: int
    ) -> ProviderStream:
        stream_options = dict(payload.get("stream_options") or {})
        stream_options["include_usage"] = True
        upstream_payload = {
            **payload,
            "model": upstream_model,
            "stream": True,
            "stream_options": stream_options,
        }
        client = self._client(timeout_seconds)
        request = client.build_request(
            "POST", self._url(), headers=self._headers(), json=upstream_payload
        )
        try:
            response = await client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            await client.aclose()
            raise GatewayError(
                "DeepSeek流式请求超时",
                status_code=504,
                error_type="upstream_error",
                code="upstream_timeout",
            ) from exc
        except httpx.HTTPError as exc:
            await client.aclose()
            raise GatewayError(
                "无法连接DeepSeek",
                status_code=502,
                error_type="upstream_error",
                code="upstream_connection_error",
            ) from exc
        if not response.is_success:
            body = await response.aread()
            error = _upstream_error(response, body)
            await response.aclose()
            await client.aclose()
            raise error
        return DeepSeekStream(client, response)
