"""API tests for Skill catalog metadata and privacy boundaries."""

from __future__ import annotations

from apps.api.dependencies import get_skill_catalog
from apps.api.main import app
from apps.api.routes.skills import list_skills


def test_skills_route_returns_metadata_without_bodies() -> None:
    assert "/api/skills" in {route.path for route in app.routes}

    payload = list_skills(get_skill_catalog())
    rendered = repr(payload)
    assert payload["schema_version"] == "klara.skills-catalog.v1"
    assert payload["body_loading"] == "on_demand"
    assert payload["skills"]
    assert "Use the repository as the source of truth" not in rendered
    assert not any("C:/" in str(item["source"]) for item in payload["skills"])
