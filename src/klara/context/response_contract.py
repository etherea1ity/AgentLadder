"""Question-bound final-answer projection for exact fields and safety refusals."""

from __future__ import annotations

import json

from klara.core.loop import FinalAnswerDecision, LoopControllerEvent
from klara.core.messages import KlaraMessage
from klara.core.tools import ToolResult


class ResponseContractController:
    """Enforce explicit field limits without trusting a model to redact metadata."""

    def __init__(self) -> None:
        self._user_input = ""
        self._field_limited = False
        self._destructive_home_request = False
        self._followup_rule_request = False
        self._projection: str | None = None
        self._events: list[LoopControllerEvent] = []

    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        del run_id
        self._user_input = user_input
        compact = " ".join(user_input.casefold().split())
        self._field_limited = any(
            cue in compact
            for cue in ("only tell", "only return", "only say", "只说", "仅说", "只列")
        )
        self._destructive_home_request = (
            any(cue in compact for cue in ("home directory", "home folder", "主目录", "用户目录"))
            and any(cue in compact for cue in ("delete", "remove", "删除", "清空"))
        )
        self._followup_rule_request = any(
            cue in compact for cue in ("final rule", "最终规则")
        ) and any(cue in compact for cue in ("continue", "继续"))
        self._projection = None
        self._events = []

    def system_prompt_suffix(self) -> str:
        if not self._followup_rule_request:
            return ""
        return (
            "<followup_response_contract>When the user asks to continue and state "
            "the final rule, derive that rule from the latest explicit user correction "
            "already present in the transcript. State the corrected instruction itself; "
            "do not claim the context is missing.</followup_response_contract>"
        )

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        if not self._field_limited:
            return
        for result in results:
            if not result.ok or result.name not in {
                "skills_list",
                "schedule_list",
                "task_list",
            }:
                continue
            projection = _project_exact_fields(result)
            if projection:
                self._projection = projection
                self._events.append(
                    LoopControllerEvent(
                        type="response_contract.projection_ready",
                        payload={
                            "tool": result.name,
                            "projection_kind": "explicit_fields_only",
                            "source_content_exposed": False,
                        },
                    )
                )

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        if self._projection is not None:
            return FinalAnswerDecision(
                allowed=True,
                reason="explicit_field_projection",
                replacement_content=self._projection,
            )
        if self._destructive_home_request:
            if _has_han(self._user_input):
                replacement = "我不能删除用户主目录，也不能超出已授权的工作区范围。"
            else:
                replacement = (
                    "I cannot delete a home directory or exceed the authorized "
                    "workspace scope."
                )
            return FinalAnswerDecision(
                allowed=True,
                reason="destructive_scope_refusal",
                replacement_content=replacement,
            )
        if _looks_incomplete_final_answer(
            content,
            short_rule_answer=self._followup_rule_request,
        ):
            return FinalAnswerDecision(
                allowed=False,
                reason="incomplete_final_answer",
                feedback=(
                    "The previous response ended as an unfinished heading or block. "
                    "Complete the answer now and include the requested facts. Do not "
                    "repeat an empty heading."
                ),
            )
        return FinalAnswerDecision(allowed=True, reason="response_contract_ready")

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        return messages

    def drain_events(self) -> tuple[LoopControllerEvent, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events


def _project_exact_fields(result: ToolResult) -> str:
    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    if result.name == "skills_list":
        records = payload.get("skills", [])
        pairs = [(item.get("name"), item.get("scope")) for item in records if isinstance(item, dict)]
    elif result.name == "schedule_list":
        records = payload.get("schedules", [])
        pairs = [(item.get("title"), item.get("status")) for item in records if isinstance(item, dict)]
    else:
        records = payload.get("tasks", [])
        pairs = [(item.get("title"), item.get("state")) for item in records if isinstance(item, dict)]
    lines = [
        f"{left} — {right}."
        for left, right in pairs
        if isinstance(left, str) and left.strip() and isinstance(right, str) and right.strip()
    ]
    return "\n".join(lines)


def _has_han(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def _looks_incomplete_final_answer(
    content: str,
    *,
    short_rule_answer: bool = False,
) -> bool:
    """Reject visibly dangling headings and unclosed fenced blocks."""

    stripped = content.strip()
    if not stripped:
        return True
    if stripped.count("```") % 2:
        return True
    if stripped.endswith((":", "：")):
        return True
    return short_rule_answer and len(stripped) < 6
