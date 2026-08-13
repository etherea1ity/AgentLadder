"""Integration tests for progressive Skill loading and public trace safety."""

from __future__ import annotations

import json
from pathlib import Path

from klara.core.hooks import HookManager
from klara.core.loop import KlaraLoop
from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.skills import SkillCatalog, SkillListTool, SkillRuntimeController, SkillViewTool
from klara.tools.executor import ToolExecutor


class _Recorder:
    def __init__(self) -> None:
        self.events = []

    def on_event(self, event) -> None:
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
                tool_calls=(ToolCall(id="view-1", name="skill_view", arguments={"name": "demo"}),),
            )
        return ModelResponse(content="Used the procedure.")


def test_skill_body_enters_next_prompt_but_not_public_trace(tmp_path: Path) -> None:
    package = tmp_path / "skills" / "demo"
    package.mkdir(parents=True)
    private_body = "PRIVATE-SKILL-BODY use a bounded checklist"
    (package / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo procedure.\nversion: 1.0.0\ntools:\npermissions:\ndependencies:\nreferences:\n---\n"
        + private_body,
        encoding="utf-8",
    )
    catalog = SkillCatalog.discover(
        built_in_root=None,
        user_root=None,
        project_root=tmp_path / "skills",
        allowed_tools=("skills_list", "skill_view"),
    )
    recorder = _Recorder()
    llm = _SkillLlm()
    result = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([SkillListTool(catalog), SkillViewTool(catalog)]),
        hooks=HookManager([recorder]),
        controllers=(SkillRuntimeController(catalog),),
        system_prompt="base",
    ).run("Use demo", run_id="skill-run")

    public_trace = json.dumps(
        [event.to_public_dict() for event in recorder.events], ensure_ascii=False
    )
    assert private_body not in llm.prompts[0]
    assert private_body in llm.prompts[1]
    assert private_body not in public_trace
    assert "skills.selected" in public_trace
    assert "skills.loaded" in public_trace
    assert result.final_answer == "Used the procedure."
