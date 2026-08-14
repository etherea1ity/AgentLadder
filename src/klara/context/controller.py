"""Loop controller for context assembly, budgets, and private summaries."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from klara.app.user_context import UserContext
from klara.context.assembly import ContextAssembly, WorkspaceProfile
from klara.context.budget import compact_transcript, estimate_message_tokens
from klara.context.policy import ContextPolicy
from klara.core.loop import FinalAnswerDecision, LoopControllerEvent
from klara.core.messages import KlaraMessage
from klara.core.tools import ToolResult


class ContextController:
    """Assemble private prompt context and compact over-budget transcripts."""

    def __init__(
        self,
        *,
        policy: ContextPolicy,
        user_context: UserContext,
        capabilities: tuple[str, ...],
        workspace_root: Path,
    ) -> None:
        self.policy = policy
        self.user_context = user_context
        self.capabilities = capabilities
        self.workspace = WorkspaceProfile.discover(workspace_root)
        self.session_summary = ""
        self._events: list[LoopControllerEvent] = []

    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        self.session_summary = ""
        self._events = [
            LoopControllerEvent(
                type="context.assembled",
                payload={
                    "schema_version": "klara.context.v1",
                    "project_name": self.workspace.project_name,
                    "recognized_instruction_file_count": len(self.workspace.instruction_files),
                    "user_locale": self.user_context.locale,
                    "user_timezone": self.user_context.timezone,
                    "capability_count": len(self.capabilities),
                    "private_prompt_material_exposed": False,
                },
            )
        ]

    def system_prompt_suffix(self) -> str:
        return ContextAssembly(
            workspace=self.workspace,
            user=self.user_context,
            capabilities=self.capabilities,
            session_summary=self.session_summary,
        ).to_prompt()

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        return None

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        return FinalAnswerDecision(allowed=True, reason="context_ready")

    def should_compact(self, messages: list[KlaraMessage]) -> bool:
        estimated = estimate_message_tokens(
            messages, chars_per_token=self.policy.chars_per_token
        )
        old_tool_too_large = any(
            message.role == "tool"
            and len(message.content) > self.policy.tool_result_max_chars
            for message in messages[: -self.policy.recent_messages]
        )
        return (
            estimated > self.policy.transcript_budget_tokens
            or old_tool_too_large
        )

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        estimated = estimate_message_tokens(
            messages, chars_per_token=self.policy.chars_per_token
        )
        self._events.append(
            LoopControllerEvent(
                type="context.budget_evaluated",
                payload={
                    "estimated_transcript_tokens": estimated,
                    "transcript_budget_tokens": self.policy.transcript_budget_tokens,
                    "message_count": len(messages),
                    "over_budget": estimated > self.policy.transcript_budget_tokens,
                    "estimator": (
                        f"ascii_chars/{self.policy.chars_per_token}+non_ascii_chars"
                    ),
                },
            )
        )
        if not self.should_compact(messages):
            return messages
        prepared, summary, metrics = compact_transcript(
            messages,
            policy=self.policy,
            previous_summary=self.session_summary,
        )
        self.session_summary = summary
        self._events.append(
            LoopControllerEvent(
                type="context.compacted",
                payload={
                    **metrics,
                    "strategy": "tool_micro_compaction_then_extractive_session_summary",
                    "summary_content_exposed": False,
                },
            )
        )
        return prepared

    def recover_prompt_too_long(
        self,
        messages: list[KlaraMessage],
        *,
        attempt: int,
    ) -> list[KlaraMessage]:
        """Force a tighter deterministic budget after provider rejection."""

        tightened_budget = max(128, int(self.policy.transcript_budget_tokens * 0.7))
        tightened = replace(
            self.policy,
            max_input_tokens=(
                self.policy.reserved_system_tokens
                + self.policy.reserved_output_tokens
                + tightened_budget
            ),
            recent_messages=max(
                self.policy.minimum_recent_messages,
                self.policy.recent_messages - attempt,
            ),
        )
        prepared, summary, metrics = compact_transcript(
            messages,
            policy=tightened,
            previous_summary=self.session_summary,
        )
        self.session_summary = summary
        self._events.extend(
            [
                LoopControllerEvent(
                    type="context.prompt_recovery_applied",
                    payload={
                        "attempt": attempt,
                        "original_budget_tokens": self.policy.transcript_budget_tokens,
                        "recovery_budget_tokens": tightened.transcript_budget_tokens,
                        "summary_content_exposed": False,
                    },
                ),
                LoopControllerEvent(
                    type="context.compacted",
                    payload={
                        **metrics,
                        "strategy": "provider_rejection_forced_compaction",
                        "summary_content_exposed": False,
                        "prompt_recovery_attempt": attempt,
                    },
                ),
            ]
        )
        return prepared

    def drain_events(self) -> tuple[LoopControllerEvent, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events

    def private_checkpoint(self) -> dict[str, object]:
        """Persist private compaction state that tool-observation replay cannot rebuild."""

        return {
            "schema_version": "klara.context-controller-checkpoint.v1",
            "session_summary": self.session_summary,
        }

    def restore_private_checkpoint(self, value: dict[str, object]) -> None:
        """Restore the exact private summary before the resumed model call."""

        if value.get("schema_version") != "klara.context-controller-checkpoint.v1":
            raise ValueError("context_controller_checkpoint_schema_unsupported")
        summary = value.get("session_summary")
        if not isinstance(summary, str):
            raise ValueError("context_controller_checkpoint_summary_invalid")
        if len(summary) > self.policy.summary_max_chars:
            raise ValueError("context_controller_checkpoint_summary_oversized")
        self.session_summary = summary
