"""Environment and dotenv helpers for Klara infrastructure."""

from __future__ import annotations

import os
from pathlib import Path


def get_env_secret(name: str, *, dotenv_path: str | Path | None = None) -> str:
    """Return a secret from process env or an optional dotenv file.

    Args:
        name: Environment variable name to read.
        dotenv_path: Optional dotenv path used only when process env is empty.

    Returns:
        Secret value or an empty string when absent.
    """

    # Process env wins so callers can override local files in tests and shells.
    value = os.environ.get(name)
    if value:
        return value
    if dotenv_path is None:
        return ""
    return _read_dotenv_value(Path(dotenv_path), name)


def _read_dotenv_value(path: Path, name: str) -> str:
    """Read one dotenv key without exporting all secrets into process env."""

    if not path.exists():
        return ""
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        return _unquote_env_value(value.strip())
    return ""


def _unquote_env_value(value: str) -> str:
    """Remove simple dotenv quotes from a value."""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
