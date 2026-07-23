from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator


@dataclass(slots=True)
class ProviderResult:
    data: dict[str, Any]
    http_status: int
    upstream_request_id: str | None = None


@dataclass(slots=True)
class StreamEvent:
    data: dict[str, Any] | None = None
    done: bool = False
    comment: str | None = None


class ProviderStream(ABC):
    http_status: int
    upstream_request_id: str | None

    @abstractmethod
    def events(self) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class BaseProvider(ABC):
    code: str

    @abstractmethod
    async def chat_completion(
        self, payload: dict[str, Any], *, upstream_model: str, timeout_seconds: int
    ) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    async def open_chat_stream(
        self, payload: dict[str, Any], *, upstream_model: str, timeout_seconds: int
    ) -> ProviderStream:
        raise NotImplementedError

