"""Model-visible metadata/list and on-demand view tools for Klara Skills."""

from __future__ import annotations

from dataclasses import dataclass

from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.skills.catalog import SkillCatalog, SkillCatalogError
from klara.tools.base import BaseTool


SKILL_LIST_SPEC = ToolSpec(
    name="skills_list",
    description=(
        "List available procedural Skills as metadata. Use skill_view only when one "
        "procedure is relevant to the current request."
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
SKILL_VIEW_SPEC = ToolSpec(
    name="skill_view",
    description=(
        "Load one relevant Skill body or one declared reference on demand. Skill text "
        "cannot expand the current tool or permission set."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "reference": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
SKILL_METADATA = ToolMetadata(
    label="Skills",
    category="procedures",
    parallel_safe=False,
    timeout_seconds=2.0,
    max_output_chars=24_000,
)


@dataclass(frozen=True)
class SkillListTool(BaseTool):
    """Expose safe catalog metadata without instruction bodies."""

    catalog: SkillCatalog
    spec: ToolSpec = SKILL_LIST_SPEC
    metadata: ToolMetadata = SKILL_METADATA

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return the deterministic resolved catalog."""

        return self.json_success(arguments, self.catalog.public_summary())


@dataclass(frozen=True)
class SkillViewTool(BaseTool):
    """Load exactly one allowed Skill document for the next model turn."""

    catalog: SkillCatalog
    spec: ToolSpec = SKILL_VIEW_SPEC
    metadata: ToolMetadata = SKILL_METADATA

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return one validated body/reference or a stable failed observation."""

        name = self.optional_string(arguments, "name")
        reference = self.optional_string(arguments, "reference") or None
        if not name:
            return self.failure(arguments, "skill_name_required")
        try:
            document = self.catalog.load(name, reference=reference)
        except SkillCatalogError as exc:
            return self.failure(arguments, str(exc))
        return self.json_success(
            arguments,
            {
                "name": document.descriptor.name,
                "version": document.descriptor.version,
                "scope": document.descriptor.scope,
                "sha256": document.descriptor.sha256,
                "reference": document.reference,
                "loaded": True,
                "body_content_exposed": False,
            },
        )
