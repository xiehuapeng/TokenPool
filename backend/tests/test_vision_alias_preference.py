from types import SimpleNamespace

import pytest
from app.services import model_router


@pytest.mark.asyncio
@pytest.mark.parametrize("canonical_available", [False, True])
async def test_alias_preference_preserves_provider_order(monkeypatch, canonical_available):
    alias = SimpleNamespace(id=1, provider_id=1, public_model="old",
                            capabilities={"vision": True, "official_alias_of": "new"})
    other = SimpleNamespace(id=2, provider_id=2, public_model="other", capabilities={"vision": True})
    canonical = SimpleNamespace(id=3, provider_id=1, public_model="new", capabilities={"vision": True})

    async def permitted(*args, **kwargs):
        return [alias, other] + ([canonical] if canonical_available else [])

    async def resolve(*args, public_model, **kwargs):
        return public_model

    monkeypatch.setattr(model_router, "list_permitted_models", permitted)
    monkeypatch.setattr(model_router, "resolve_model", resolve)
    assert await model_router.find_vision_fallback(None, user_id=1, exclude_model_id=99) == (
        "new" if canonical_available else "old")
