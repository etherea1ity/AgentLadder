from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

router = APIRouter(prefix="/api/assets", tags=["assets"])

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
_TEXT_EXTENSIONS = {".txt", ".md", ".json", ".jsonl", ".csv"}


@router.get("/local")
def get_local_asset(path: str = Query(..., min_length=1)):
    resolved = _safe_repo_path(path)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="asset_not_found")
    kind = _asset_kind(resolved)
    if kind == "text":
        return PlainTextResponse(resolved.read_text(encoding="utf-8", errors="replace"))
    return FileResponse(resolved)


def _safe_repo_path(path_value: str) -> Path:
    if not path_value or _looks_windows_absolute(path_value):
        raise HTTPException(status_code=400, detail="absolute_asset_path_not_allowed")
    repo_root = Path(".").resolve()
    path = Path(path_value)
    if path.is_absolute():
        raise HTTPException(status_code=400, detail="absolute_asset_path_not_allowed")
    resolved = (repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="asset_path_escapes_repo") from exc
    return resolved


def _asset_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _TEXT_EXTENSIONS:
        return "text"
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    return "file"


def _looks_windows_absolute(path: str) -> bool:
    return len(path) >= 3 and path[1] == ":" and path[2] in {"\\", "/"}
