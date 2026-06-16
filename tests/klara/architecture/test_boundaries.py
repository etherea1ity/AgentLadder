from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "src" / "klara" / "core"
TOOLS = ROOT / "src" / "klara" / "capabilities" / "tools"

CORE_FILES = {
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
    "klara.infra",
)

ALLOWED_TOOL_TOP_LEVEL_FILES = {"__init__.py"}
REQUIRED_TOOL_PACKAGE_FILES = {"__init__.py", "schema.py", "tool.py"}


def test_core_does_not_import_future_layers() -> None:
    """Core must not import layers that belong outside the runtime kernel."""

    # Violations are accumulated so the failure explains every bad import.
    violations: list[str] = []
    # Walk each core file to inspect imports without executing code.
    for path in CORE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Inspect every AST node because imports may appear below the module top.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue

            # Check every imported module against future-layer prefixes.
            for name in names:
                if name.startswith(FORBIDDEN_CORE_IMPORT_PREFIXES):
                    violations.append(f"{path.name}: {name}")

    assert violations == []


def test_core_file_set_stays_explicit() -> None:
    """Core should not grow files without an architecture decision."""

    # File whitelist makes core growth visible in test output.
    actual = {path.name for path in CORE.glob("*.py")}

    assert actual == CORE_FILES


def test_concrete_tools_use_package_layout() -> None:
    """Concrete tools should live in readable packages, not flat files."""

    # The tools root only re-exports concrete packages.
    flat_files = sorted(
        path.name
        for path in TOOLS.glob("*.py")
        if path.name not in ALLOWED_TOOL_TOP_LEVEL_FILES
    )
    # Each tool package keeps schema and execution concerns inspectable.
    missing_required_files: list[str] = []
    tool_packages = [
        path for path in TOOLS.iterdir() if path.is_dir() and not path.name.startswith("__")
    ]
    for tool_package in tool_packages:
        missing = REQUIRED_TOOL_PACKAGE_FILES - {
            path.name for path in tool_package.glob("*.py")
        }
        if missing:
            missing_required_files.append(f"{tool_package.name}: {sorted(missing)}")

    assert flat_files == []
    assert missing_required_files == []
