from pydantic import BaseModel, Field


class ModelPreferenceUpdate(BaseModel):
    model: str = Field(min_length=1, max_length=120)


class ModelPreferenceView(BaseModel):
    gateway_model: str
    selected_model: str | None
    selection_source: str
