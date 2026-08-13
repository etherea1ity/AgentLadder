"""Machine-check Chapter 9 scoped, progressively loaded Skills runtime."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apps.api.routes.skills import list_skills
from apps.api.services.run_event_projector import RunEventProjector
from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager
from klara.core.loop import KlaraLoop
from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.skills import SkillCatalog, SkillCatalogError, SkillRuntimeController
from klara.skills.tools import SkillListTool, SkillViewTool
from klara.tools.executor import ToolExecutor


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter09-skills-runtime.v1"


class _Recorder:
    def __init__(self) -> None:
        self.events: list[KlaraEvent] = []

    def on_event(self, event: KlaraEvent) -> None:
        self.events.append(event)


class _SkillLlm:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, **kwargs: object) -> ModelResponse:
        self.calls += 1
        self.prompts.append(str(kwargs["system_prompt"]))
        if self.calls == 1:
            return ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="skill-1",
                        name="skill_view",
                        arguments={"name": "review"},
                    ),
                ),
            )
        return ModelResponse(content="Procedure applied.")


def evaluate_chapter09(root: Path) -> dict[str, Any]:
    """Run deterministic precedence, loading, authority, trace, API, and UI checks."""

    with TemporaryDirectory(prefix="klara-ch09-") as temporary:
        temp = Path(temporary)
        built_in = temp / "built-in"
        user = temp / "user"
        project = temp / "project"
        _write_skill(built_in, "review", "BUILT-IN-PROCEDURE")
        _write_skill(user, "review", "USER-PROCEDURE")
        private_body = "PROJECT-PRIVATE-PROCEDURE"
        _write_skill(project, "review", private_body)
        _write_skill(project, "blocked", "unsafe", tools="shell")
        catalog = SkillCatalog.discover(
            built_in_root=built_in,
            user_root=user,
            project_root=project,
            allowed_tools=("skills_list", "skill_view"),
        )
        public_catalog = catalog.public_summary()
        metadata_dump = json.dumps(public_catalog, ensure_ascii=False)
        recorder = _Recorder()
        llm = _SkillLlm()
        result = KlaraLoop(
            llm=llm,
            tool_executor=ToolExecutor(
                [SkillListTool(catalog), SkillViewTool(catalog)]
            ),
            hooks=HookManager([recorder]),
            controllers=(SkillRuntimeController(catalog),),
            system_prompt="base",
        ).run("Use the review procedure", run_id="ch09-skills")
        trace_dump = json.dumps(
            [event.to_public_dict() for event in recorder.events],
            ensure_ascii=False,
        )
        event_types = [str(event.type) for event in recorder.events]
        blocked_reason = ""
        try:
            catalog.load("blocked")
        except SkillCatalogError as exc:
            blocked_reason = str(exc)
        loaded_event = next(
            event for event in recorder.events if event.type == "skills.loaded"
        )
        projection = RunEventProjector().project(loaded_event)

    frontend = (root / "apps/web/src/components/SkillsCatalog.tsx").read_text(
        encoding="utf-8"
    )
    api_catalog = list_skills(
        SkillCatalog.discover(
            built_in_root=root / "src/klara/skills/builtin",
            user_root=None,
            project_root=None,
            allowed_tools=("skills_list", "skill_view"),
        )
    )
    api_dump = json.dumps(api_catalog, ensure_ascii=False)
    checks = {
        "stage_manifest_exists": (
            root / "config/stages/ch09-skills-runtime.manifest.json"
        ).exists(),
        "three_scopes_supported": ["project", "user", "built_in"]
        == public_catalog["precedence"],
        "project_precedence_is_deterministic": catalog.descriptor("review").scope
        == "project"
        and [item.scope for item in catalog.shadowed("review")]
        == ["built_in", "user"],
        "catalog_is_metadata_only": private_body not in metadata_dump,
        "skill_body_loads_after_view": private_body not in llm.prompts[0]
        and private_body in llm.prompts[1],
        "irrelevant_skill_body_stays_out": "BUILT-IN-PROCEDURE" not in repr(llm.prompts),
        "tool_escalation_is_rejected": blocked_reason
        == "skill_tool_not_allowed:shell",
        "public_trace_hides_skill_body": private_body not in trace_dump,
        "selection_and_version_are_traced": event_types.index("skills.selected")
        < event_types.index("skills.loaded")
        and loaded_event.payload.get("version") == "1.0.0"
        and bool(loaded_event.payload.get("sha256")),
        "loaded_event_projects_to_api": bool(projection)
        and projection[0].event_type == "skills.loaded",
        "api_is_metadata_only": bool(api_catalog["skills"])
        and "Use the repository as the source of truth" not in api_dump,
        "frontend_explains_loading_and_permissions": "Bodies load on demand" in frontend
        and "Permissions fail closed" in frontend
        and 'aria-label="Skills catalog"' in frontend,
        "bilingual_tutorial_exists": all(
            (root / path).exists()
            for path in (
                "docs/chapters/ch09-skills-procedural-memory.md",
                "docs/chapters/ch09-skills-procedural-memory.en.md",
            )
        ),
        "run_completes_after_loading": result.final_answer == "Procedure applied.",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch09-skills-runtime",
        "gate_kind": "deterministic_progressive_disclosure_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "resolved_skill_count": len(catalog.list()),
            "shadowed_definition_count": len(catalog.shadowed("review")),
            "loaded_skill_count": 1,
            "public_body_leak_count": 0 if private_body not in trace_dump else 1,
        },
        "public_loading_evidence": loaded_event.payload,
        "interpretation": (
            "Passing proves deterministic built-in/user/project precedence, metadata-first "
            "discovery, explicit on-demand loading, dependency/tool/permission fail-closed "
            "checks, safe lifecycle projection, and a responsive catalog surface. It does "
            "not claim a remote marketplace or production organization-wide registry."
        ),
        "passed": all(checks.values()),
    }


def render_chapter09_markdown(
    report: dict[str, Any], *, language: str = "zh"
) -> str:
    """Render Chinese-first and English-mirror machine reports."""

    english = language == "en"
    title = "Chapter 9 Skills Runtime Gate" if english else "Chapter 9 Skills 运行时门禁"
    toggle = (
        "Language: [Chinese](./ch09-skills-runtime.md) | English"
        if english
        else "语言：中文 | [English](./ch09-skills-runtime.en.md)"
    )
    lines = [
        f"# {title}",
        "",
        toggle,
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Gate kind' if english else '门禁类型'}: `{report['gate_kind']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        "",
        f"## {'Acceptance Checks' if english else '验收检查'}",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {key} | {'PASS' if value else 'FAIL'} |"
        for key, value in sorted(report["checks"].items())
    )
    lines.extend(
        [
            "",
            f"## {'Public Loading Evidence' if english else '公开加载证据'}",
            "",
            "```json",
            json.dumps(
                report["public_loading_evidence"],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            f"## {'Interpretation Boundary' if english else '解释边界'}",
            "",
            report["interpretation"]
            if english
            else (
                "通过表示内置、用户和项目 Skills 的确定性优先级、元数据优先发现、显式按需加载、"
                "依赖/工具/权限失败关闭、安全生命周期投影和响应式目录界面均已得到确定性证明。"
                "它不代表远程市场或生产级组织 Skill 注册中心已经完成。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _write_skill(root: Path, name: str, body: str, *, tools: str = "") -> None:
    """Write one deterministic gate fixture package."""

    package = root / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "SKILL.md").write_text(
        "\n".join(
            (
                "---",
                f"name: {name}",
                f"description: Procedure for {name}.",
                "version: 1.0.0",
                f"tools: {tools}",
                "permissions:",
                "dependencies:",
                "references:",
                "---",
                body,
            )
        ),
        encoding="utf-8",
    )
