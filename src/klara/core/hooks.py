"""Hook fanout and JSONL tracing for Klara's core loop."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Protocol

from klara.core.events import KlaraEvent
from klara.core.tools import ToolCall, ToolResult


@dataclass(frozen=True)
class HookDecision:
    """Minimal lifecycle decision returned by placement hooks."""

    allowed: bool = True
    reason: str = ""
    public_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class UserPromptSubmitContext:
    """Context exposed when a user prompt enters the runtime."""

    run_id: str
    user_input: str


@dataclass(frozen=True)
class PreToolUseContext:
    """Context exposed immediately before a tool may execute."""

    run_id: str
    turn_index: int
    tool_call: ToolCall


@dataclass(frozen=True)
class PostToolUseContext:
    """Context exposed after an executed tool returns an observation."""

    run_id: str
    turn_index: int
    tool_call: ToolCall
    tool_result: ToolResult


@dataclass(frozen=True)
class PreCompactContext:
    """Public placement context immediately before transcript compaction."""

    run_id: str
    turn_index: int
    message_count: int


@dataclass(frozen=True)
class StopContext:
    """Context exposed just before the run emits completion."""

    run_id: str
    stop_reason: str


class KlaraHook(Protocol):
    """Protocol for observers or guards attached to loop lifecycle events."""

    def on_event(self, event: KlaraEvent) -> None:
        """Handle one loop event.

        Args:
            event: Public lifecycle event emitted by core.
        """

        ...


class HookManager:
    """Fan out events while isolating hook failures from loop execution.

    The runtime uses hooks mainly for trace output. Later extensions can
    attach policy checks, compaction, memory review, or streaming projectors
    without changing the loop contract.
    """

    def __init__(self, hooks: list[KlaraHook] | None = None) -> None:
        """Create a hook manager with optional initial hooks.

        Args:
            hooks: Hooks that should receive every emitted event.
        """

        # Registered hooks are ordered so trace output follows lifecycle order.
        self._hooks = hooks or []
        # Failures are recorded for result visibility instead of crashing the run.
        self.failures: list[tuple[str, str]] = []

    def register(self, hook: KlaraHook) -> None:
        """Attach one more hook to the lifecycle fanout.

        Args:
            hook: Hook implementation to call for future events.
        """

        self._hooks.append(hook)

    def emit(self, event: KlaraEvent) -> None:
        """Send an event to every hook and record hook-level failures.

        Args:
            event: Public lifecycle event emitted by the loop.
        """

        # Visit hooks sequentially so trace and policy hooks see stable order.
        for hook in self._hooks:
            try:
                hook.on_event(event)
            except Exception as exc:  # pragma: no cover - exact hook errors vary
                # Hook failures are runtime observations, not loop failures.
                self.failures.append((event.type, f"{type(exc).__name__}: {exc}"))

    def user_prompt_submit(self, context: UserPromptSubmitContext) -> HookDecision:
        """Run optional user-prompt placement hooks.

        Hook failures are isolated and default to allow so observer bugs do not
        break core run execution.
        """

        return self._decision_placement(
            "user_prompt_submit",
            "on_user_prompt_submit",
            context,
        )

    def pre_tool_use(self, context: PreToolUseContext) -> HookDecision:
        """Run optional pre-tool placement hooks.

        Any explicit block prevents the tool call from executing. Hook failures
        are recorded and default to allow because this chapter only teaches
        placement, not a complete permission engine.
        """

        return self._decision_placement(
            "pre_tool_use",
            "on_pre_tool_use",
            context,
        )

    def post_tool_use(self, context: PostToolUseContext) -> None:
        """Run optional post-tool placement hooks without affecting the loop."""

        self._notify_placement("post_tool_use", "on_post_tool_use", context)

    def pre_compact(self, context: PreCompactContext) -> None:
        """Notify hooks before private transcript material is compacted."""

        self._notify_placement("pre_compact", "on_pre_compact", context)

    def stop(self, context: StopContext) -> None:
        """Run optional stop placement hooks without affecting completion."""

        self._notify_placement("stop", "on_stop", context)

    def _decision_placement(
        self,
        placement_name: str,
        method_name: str,
        context: object,
    ) -> HookDecision:
        """Call decision hooks and aggregate their allow/block decisions."""

        final_decision = HookDecision()
        for hook in self._hooks:
            handler = getattr(hook, method_name, None)
            if handler is None:
                continue
            try:
                decision = handler(context)
            except Exception as exc:  # pragma: no cover - exact hook errors vary
                self.failures.append(
                    (placement_name, f"{type(exc).__name__}: {exc}")
                )
                continue
            if decision is None:
                continue
            if not isinstance(decision, HookDecision):
                decision = HookDecision(
                    allowed=bool(getattr(decision, "allowed", True)),
                    reason=str(getattr(decision, "reason", "")),
                    public_metadata=dict(
                        getattr(decision, "public_metadata", {}) or {}
                    ),
                )
            if not decision.allowed:
                return decision
            if decision.reason or decision.public_metadata:
                final_decision = decision
        return final_decision

    def _notify_placement(
        self,
        placement_name: str,
        method_name: str,
        context: object,
    ) -> None:
        """Call notification placement hooks and isolate failures."""

        for hook in self._hooks:
            handler = getattr(hook, method_name, None)
            if handler is None:
                continue
            try:
                handler(context)
            except Exception as exc:  # pragma: no cover - exact hook errors vary
                self.failures.append(
                    (placement_name, f"{type(exc).__name__}: {exc}")
                )


class JsonlTraceHook:
    """Persist public lifecycle events as newline-delimited JSON."""

    def __init__(self, path: Path) -> None:
        """Create a trace hook for one JSONL file.

        Args:
            path: Destination file for event lines.
        """

        # Path stays outside core policy so the harness can choose trace storage.
        self.path = path

    def on_event(self, event: KlaraEvent) -> None:
        """Append one public event to the JSONL trace file.

        Args:
            event: Public lifecycle event to persist.
        """

        # Ensure local trace directories exist before appending the event.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_public_dict(), ensure_ascii=False) + "\n")
