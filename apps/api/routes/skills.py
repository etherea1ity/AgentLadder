"""Read-only API for the resolved Klara Skill catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.dependencies import get_skill_catalog
from apps.api.schemas import ListSkillsResponse
from klara.skills import SkillCatalog


router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=ListSkillsResponse)
def list_skills(catalog: SkillCatalog = Depends(get_skill_catalog)) -> dict[str, object]:
    """Return resolved metadata without reading or returning Skill bodies."""

    return catalog.public_summary()
