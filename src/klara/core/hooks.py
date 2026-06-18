"""Hook fanout and JSONL tracing for Klara's core loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from klara.core.events import KlaraEvent


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
