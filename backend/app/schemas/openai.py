from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1, max_length=160)
    messages: list[dict[str, Any]] = Field(min_length=1)
    stream: bool = False


class OpenAIModel(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "team-gateway"


class OpenAIModelList(BaseModel):
    object: str = "list"
    data: list[OpenAIModel]

