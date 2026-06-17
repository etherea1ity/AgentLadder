from __future__ import annotations

import hashlib
import re

_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_slug(text: str, *, max_words: int = 6) -> str:
    words = _WORD_RE.findall(text.lower())
    skip = {"a", "an", "the", "of", "and", "for", "to", "in", "on", "with", "through"}
    kept = [w for w in words if w not in skip]
    return "_".join((kept or words or ["untitled"])[:max_words])


def stable_paper_id(title: str, year: int | str | None = None, *, existing: set[str] | None = None) -> str:
    """Generate a stable repo-safe paper id from bibliographic metadata."""
    slug = normalize_slug(title)
    suffix = str(year) if year else "unknown"
    base = re.sub(r"_+", "_", f"paper_{slug}_{suffix}").strip("_")[:80]
    existing = existing or set()
    if base not in existing:
        return base
    digest = hashlib.sha1(f"{title}|{year}".encode("utf-8")).hexdigest()[:8]
    candidate = f"{base[:71]}_{digest}"
    counter = 2
    while candidate in existing:
        candidate = f"{base[:68]}_{digest}_{counter}"
        counter += 1
    return candidate


def is_valid_paper_id(paper_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_]{1,80}", paper_id))
