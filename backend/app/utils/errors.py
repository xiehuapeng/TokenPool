from fastapi import Request
from fastapi.responses import JSONResponse

from app.utils.redaction import redact_secrets


class GatewayError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        error_type: str = "invalid_request_error",
        code: str = "invalid_request",
        param: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = redact_secrets(message)
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.param = param
        self.headers = headers or {}


async def gateway_error_handler(_request: Request, exc: GatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "message": exc.message,
                "type": exc.error_type,
                "param": exc.param,
                "code": exc.code,
            }
        },
    )
