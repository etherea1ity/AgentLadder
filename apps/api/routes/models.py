from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.dependencies import get_default_model, get_model_options
from apps.api.schemas import ListModelsResponse, ModelOption

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=ListModelsResponse)
def list_models(
    models: list[ModelOption] = Depends(get_model_options),
    default_model: str = Depends(get_default_model),
):
    return ListModelsResponse(default_model=default_model, models=models)
