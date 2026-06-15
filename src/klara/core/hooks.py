from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from klara.core.events import KlaraEvent


class KlaraHook(Protocol):
    def on_event(self, event: KlaraEvent) -> None:
        ...


class HookManager:
    def __init__(self, hooks: list[KlaraHook] | None = None) -> None:
        self._hooks = hooks or []
        self.failures: list[tuple[str, str]] = []

    def register(self, hook: KlaraHook) -> None:
        self._hooks.append(hook)

    def emit(self, event: KlaraEvent) -> None:
        for hook in self._hooks:
            try:
                hook.on_event(event)
            except Exception as exc:  # pragma: no cover - exact hook errors vary
                self.failures.append((event.type, f"{type(exc).__name__}: {exc}"))


class JsonlTraceHook:
    def __init__(self, path: Path) -> None:
        self.path = path

    def on_event(self, event: KlaraEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_public_dict(), ensure_ascii=False) + "\n")
