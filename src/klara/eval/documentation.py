"""Repository-native validation for bilingual tutorial and report documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


SCORER_VERSION = "klara.documentation-validator.v1"
LINK_PATTERN = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
CODE_FENCE_PATTERN = re.compile(r"^```", re.MULTILINE)


@dataclass(frozen=True)
class DocumentPairResult:
    """Validation result for one Chinese-first and English-mirror pair."""

    chinese_path: str
    english_path: str
    checks: dict[str, bool]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether all bilingual checks pass."""

        return all(self.checks.values())

    def to_dict(self) -> dict[str, object]:
        """Serialize the pair result."""

        return {
            "chinese_path": self.chinese_path,
            "english_path": self.english_path,
            "checks": self.checks,
            "failures": list(self.failures),
            "passed": self.passed,
        }


def validate_pair(root: Path, chinese_path: Path, english_path: Path) -> DocumentPairResult:
    """Validate structure, local links, toggles, fences, and details tags."""

    chinese = chinese_path.read_text(encoding="utf-8")
    english = english_path.read_text(encoding="utf-8")
    failures: list[str] = []
    zh_headings = HEADING_PATTERN.findall(chinese)
    en_headings = HEADING_PATTERN.findall(english)
    checks = {
        "heading_count_parity": len(zh_headings) == len(en_headings),
        "heading_level_parity": [level for level, _ in zh_headings]
        == [level for level, _ in en_headings],
        "code_fence_parity": len(CODE_FENCE_PATTERN.findall(chinese))
        == len(CODE_FENCE_PATTERN.findall(english)),
        "details_balanced_chinese": chinese.count("<details>")
        == chinese.count("</details>"),
        "details_balanced_english": english.count("<details>")
        == english.count("</details>"),
        "english_toggle_present": english_path.name in chinese,
        "chinese_toggle_present": chinese_path.name in english,
        "chinese_local_links_exist": not _broken_links(root, chinese_path, chinese),
        "english_local_links_exist": not _broken_links(root, english_path, english),
    }
    for key, passed in checks.items():
        if not passed:
            failures.append(key)
    failures.extend(
        f"chinese_broken_link:{link}" for link in _broken_links(root, chinese_path, chinese)
    )
    failures.extend(
        f"english_broken_link:{link}" for link in _broken_links(root, english_path, english)
    )
    return DocumentPairResult(
        chinese_path=chinese_path.relative_to(root).as_posix(),
        english_path=english_path.relative_to(root).as_posix(),
        checks=checks,
        failures=tuple(sorted(set(failures))),
    )


def discover_pairs(root: Path, directories: Iterable[Path]) -> list[tuple[Path, Path]]:
    """Discover established `.md` and `.en.md` pairs in selected directories."""

    pairs: list[tuple[Path, Path]] = []
    for directory in directories:
        if not directory.exists():
            continue
        # Chinese files own the pair; English mirrors never create another pair.
        for chinese in sorted(directory.glob("*.md")):
            if chinese.name.endswith(".en.md"):
                continue
            english = chinese.with_name(f"{chinese.stem}.en.md")
            if english.exists():
                pairs.append((chinese, english))
    return pairs


def _broken_links(root: Path, document_path: Path, text: str) -> tuple[str, ...]:
    """Return missing local Markdown link targets while ignoring URLs and anchors."""

    failures: list[str] = []
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.strip().strip("<>").split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("/"):
            # Root-relative application routes are runtime URLs, not repository files.
            continue
        candidate = (document_path.parent / target).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            failures.append(raw_target)
            continue
        if not candidate.exists():
            failures.append(raw_target)
    return tuple(sorted(set(failures)))
