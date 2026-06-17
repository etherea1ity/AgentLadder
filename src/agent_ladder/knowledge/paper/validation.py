from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_ladder.knowledge.paper.ids import is_valid_paper_id
from agent_ladder.knowledge.paper.schema import PaperManifestEntry, PaperMetadata

REQUIRED_OVERVIEW_HEADINGS = [
    "## One Sentence Summary",
    "## Why It Matters",
    "## Core Idea",
    "## Method",
    "## Experiments",
    "## Limitations",
    "## Useful For These Questions",
    "## Key Figures",
    "## Key Tables",
]


@dataclass
class ValidationIssue:
    severity: str
    message: str
    paper_id: str | None = None


@dataclass
class ValidationReport:
    root: Path
    issues: list[ValidationIssue] = field(default_factory=list)
    per_paper: dict[str, str] = field(default_factory=dict)
    manifest_count: int = 0
    chunk_count: int = 0
    visual_count: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, severity: str, message: str, paper_id: str | None = None) -> None:
        self.issues.append(ValidationIssue(severity, message, paper_id))


def repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def has_windows_absolute_path(value: Any) -> bool:
    if isinstance(value, str):
        return bool(re.match(r"^[A-Za-z]:[\\/]", value))
    if isinstance(value, dict):
        return any(has_windows_absolute_path(v) for v in value.values())
    if isinstance(value, list):
        return any(has_windows_absolute_path(v) for v in value)
    return False


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            if line.strip():
                row = json.loads(line)
                row["__line_no"] = line_no
                rows.append(row)
    return rows


def validate_paper_corpus(root: str | Path, *, strict: bool = False, repo_root: str | Path | None = None) -> ValidationReport:
    repo_root = Path(repo_root or Path.cwd())
    root = Path(root)
    report = ValidationReport(root=root)
    manifest_path = root / "manifest.jsonl"
    if not manifest_path.exists():
        report.add("error", f"manifest.jsonl missing: {manifest_path}")
        return report

    seen_papers: set[str] = set()
    seen_titles: dict[str, str] = {}
    try:
        manifest_rows = read_jsonl(manifest_path)
    except Exception as exc:
        report.add("error", f"manifest.jsonl invalid: {exc}")
        return report

    report.manifest_count = len(manifest_rows)
    for raw in manifest_rows:
        line_no = raw.pop("__line_no", None)
        try:
            entry = PaperManifestEntry.model_validate(raw)
        except Exception as exc:
            report.add("error", f"manifest line {line_no}: schema error: {exc}")
            continue
        pid = entry.paper_id
        if not is_valid_paper_id(pid):
            report.add("error", f"invalid paper_id '{pid}'", pid)
        if pid in seen_papers:
            report.add("error", f"duplicate paper_id '{pid}'", pid)
        seen_papers.add(pid)
        title_key = entry.title.lower().strip()
        if title_key in seen_titles and seen_titles[title_key] != pid:
            report.add("warning", f"duplicate title also used by {seen_titles[title_key]}", pid)
        seen_titles[title_key] = pid
        if has_windows_absolute_path(raw):
            report.add("error", "absolute Windows path found in manifest row", pid)
        if any("\\" in str(raw.get(k) or "") for k in ["source_input_path", "local_pdf_path", "processed_dir"]):
            report.add("warning", "backslash path separator found in manifest row", pid)

        processed_dir = root / "processed" / pid
        if entry.processed_dir:
            p = Path(entry.processed_dir)
            processed_dir = (repo_root / p) if not p.is_absolute() else p
        if not processed_dir.exists():
            if entry.processing_status == "metadata_only":
                report.add("warning", "metadata_only paper has no processed directory", pid)
                report.per_paper[pid] = "metadata_only"
                continue
            report.add("error", f"processed_dir missing: {processed_dir}", pid)
            report.per_paper[pid] = "failed"
            continue
        _validate_processed_paper(report, root, processed_dir, entry, repo_root)
    return report


def _validate_processed_paper(report: ValidationReport, root: Path, processed_dir: Path, entry: PaperManifestEntry, repo_root: Path) -> None:
    pid = entry.paper_id
    paper_errors_before = len(report.errors)
    metadata_path = processed_dir / "metadata.json"
    overview_path = processed_dir / "overview.md"
    chunks_path = processed_dir / "chunks.jsonl"
    visuals_path = processed_dir / "visuals.jsonl"
    for path, label in [(metadata_path, "metadata.json"), (overview_path, "overview.md"), (chunks_path, "chunks.jsonl"), (visuals_path, "visuals.jsonl")]:
        if not path.exists():
            report.add("error", f"{label} missing", pid)
    if metadata_path.exists():
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            PaperMetadata.model_validate(meta)
            if meta.get("paper_id") != pid:
                report.add("error", f"metadata.paper_id mismatch: {meta.get('paper_id')}", pid)
            if has_windows_absolute_path(meta):
                report.add("error", "absolute Windows path found in metadata", pid)
        except Exception as exc:
            report.add("error", f"metadata.json invalid: {exc}", pid)
    if overview_path.exists():
        text = overview_path.read_text(encoding="utf-8", errors="replace")
        for heading in REQUIRED_OVERVIEW_HEADINGS:
            if heading not in text:
                report.add("error" if strict_missing_overview_heading(heading) else "warning", f"overview missing heading {heading}", pid)
    if chunks_path.exists():
        _validate_chunks(report, chunks_path, pid, entry.processing_status)
    if visuals_path.exists():
        _validate_visuals(report, visuals_path, pid, repo_root)
    report.per_paper[pid] = "passed" if len(report.errors) == paper_errors_before else "failed"


def strict_missing_overview_heading(_: str) -> bool:
    return True


def _validate_chunks(report: ValidationReport, path: Path, pid: str, processing_status: str = "processed") -> None:
    seen: set[str] = set()
    try:
        rows = read_jsonl(path)
    except Exception as exc:
        report.add("error", f"chunks.jsonl invalid: {exc}", pid)
        return
    if not rows:
        if processing_status in ("metadata_only", "partial"):
            report.add("warning", f"chunks.jsonl empty (processing_status={processing_status})", pid)
        else:
            report.add("error", "chunks.jsonl empty", pid)
        return
    for row in rows:
        line_no = row.pop("__line_no", None)
        for field in ["chunk_id", "paper_id", "source_id", "section", "page_start", "page_end", "text", "token_count", "metadata"]:
            if field not in row:
                report.add("error", f"chunks line {line_no}: missing {field}", pid)
        cid = row.get("chunk_id")
        if cid in seen:
            report.add("error", f"duplicate chunk_id/source_id {cid}", pid)
        seen.add(cid)
        if row.get("paper_id") != pid:
            report.add("error", f"chunks line {line_no}: paper_id mismatch", pid)
        if not str(row.get("text") or "").strip():
            report.add("error", f"chunks line {line_no}: empty text", pid)
        if has_windows_absolute_path(row):
            report.add("error", f"chunks line {line_no}: absolute Windows path", pid)
    report.chunk_count += len(rows)


def _validate_visuals(report: ValidationReport, path: Path, pid: str, repo_root: Path) -> None:
    seen: set[str] = set()
    try:
        rows = read_jsonl(path)
    except Exception as exc:
        report.add("error", f"visuals.jsonl invalid: {exc}", pid)
        return
    for row in rows:
        line_no = row.pop("__line_no", None)
        for field in ["visual_id", "paper_id", "source_id", "visual_type", "label", "caption", "page", "image_path", "thumbnail_path", "nearby_text", "ocr_text", "visual_summary", "bbox", "metadata"]:
            if field not in row:
                if field == "label" and row.get("title"):
                    # VisualElement.model_validator copies title->label
                    row["label"] = row["title"]
                elif field in ("ocr_text", "bbox", "nearby_text", "visual_summary", "thumbnail_path", "image_path"):
                    # These fields are optional in practice
                    row[field] = None
                else:
                    report.add("error", f"visuals line {line_no}: missing {field}", pid)
        vid = row.get("visual_id")
        if vid in seen:
            report.add("error", f"duplicate visual_id/source_id {vid}", pid)
        seen.add(vid)
        if row.get("paper_id") != pid:
            report.add("error", f"visuals line {line_no}: paper_id mismatch", pid)
        for field in ["image_path", "thumbnail_path"]:
            value = row.get(field)
            if value:
                if has_windows_absolute_path(value):
                    report.add("error", f"visuals line {line_no}: absolute Windows path in {field}", pid)
                full = repo_root / str(value)
                if not full.exists():
                    report.add("error", f"visuals line {line_no}: {field} does not exist: {value}", pid)
        if has_windows_absolute_path(row):
            report.add("error", f"visuals line {line_no}: absolute Windows path", pid)
    report.visual_count += len(rows)


def render_validation_report(report: ValidationReport) -> str:
    lines = [
        "# Chapter 3 Paper Corpus Validation Report",
        "",
        f"Root: `{report.root.as_posix()}`",
        f"Validation status: {'passed' if report.ok else 'failed'}",
        f"Manifest count: {report.manifest_count}",
        f"Chunk count total: {report.chunk_count}",
        f"Visual count total: {report.visual_count}",
        f"Critical errors: {len(report.errors)}",
        f"Warnings: {len(report.warnings)}",
        "",
        "## Critical Errors",
    ]
    lines.extend([f"- {i.paper_id or 'global'}: {i.message}" for i in report.errors] or ["- none"])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {i.paper_id or 'global'}: {i.message}" for i in report.warnings] or ["- none"])
    lines.extend(["", "## Per-paper Validation Result"])
    for pid, status in sorted(report.per_paper.items()):
        lines.append(f"- {pid}: {status}")
    return "\n".join(lines) + "\n"
