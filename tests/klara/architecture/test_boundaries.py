from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "src" / "klara" / "core"

CHAPTER1_CORE_FILES = {
    "__init__.py",
    "messages.py",
    "tools.py",
    "events.py",
    "hooks.py",
    "policies.py",
    "tool_executor.py",
    "loop.py",
}

FORBIDDEN_CORE_IMPORT_PREFIXES = (
    "klara.app",
    "klara.context",
    "klara.capabilities",
    "klara.services",
    "klara.memory",
    "klara.skills",
    "klara.backend",
    "klara.eval",
    "klara.training",
)


def test_core_does_not_import_future_layers() -> None:
    violations: list[str] = []
    for path in CORE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue

            for name in names:
                if name.startswith(FORBIDDEN_CORE_IMPORT_PREFIXES):
                    violations.append(f"{path.name}: {name}")

    assert violations == []


def test_chapter1_core_file_set_stays_explicit() -> None:
    actual = {path.name for path in CORE.glob("*.py")}

    assert actual == CHAPTER1_CORE_FILES
