"""Local storage helpers for generated images."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4


def save_image_bytes(
    content: bytes,
    *,
    root: Path = Path("data/assets/images"),
    extension: str = ".png",
) -> tuple[str, str]:
    """Persist image bytes and return repo-relative path plus public URL."""

    if not content:
        raise ValueError("image content must not be empty")
    safe_extension = extension if extension.startswith(".") else f".{extension}"
    date_dir = datetime.now(UTC).strftime("%Y%m%d")
    target_dir = root / date_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{uuid4().hex}{safe_extension.lower()}"
    path.write_bytes(content)
    relative_path = path.as_posix()
    public_url = f"/api/assets/local?path={quote(relative_path, safe='/')}"
    return relative_path, public_url

