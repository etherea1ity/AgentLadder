from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_ladder.knowledge.paper.schema import PaperManifestEntry, PaperMetadata

OVERVIEW_HEADINGS = [
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

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".json", ".jsonl", ".png", ".jpg", ".jpeg", ".csv", ".xlsx"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def to_posix_repo_path(value: str | None, repo_root: Path) -> str | None:
    if not value:
        return None
    text = str(value).replace("\\", "/")
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(repo_root.resolve()).as_posix()
        except Exception:
            # Do not leak absolute paths into corpus files.
            return path.name
    return text


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def audit_source_drop(input_path: Path, output_json: Path | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "input_path": input_path.as_posix(),
        "exists": input_path.exists(),
        "file_count_by_extension": {},
        "detected_paper_candidates": [],
        "ignored_files": [],
        "possible_duplicate_papers": [],
    }
    if not input_path.exists():
        report["note"] = "input path does not exist; existing data/papers/processed corpus should be treated as already migrated source"
        if output_json:
            output_json.parent.mkdir(parents=True, exist_ok=True)
            output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    files = [p for p in input_path.rglob("*") if p.is_file()]
    counter = Counter(p.suffix.lower() or "[noext]" for p in files)
    report["file_count_by_extension"] = dict(sorted(counter.items()))
    clusters: dict[str, list[Path]] = defaultdict(list)
    for file in files:
        suffix = file.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            report["ignored_files"].append({"path": file.as_posix(), "reason": "unsupported extension"})
            continue
        key = file.parent.name if file.parent != input_path else file.stem
        clusters[key].append(file)
    for key, group in sorted(clusters.items()):
        suffixes = Counter(p.suffix.lower() for p in group)
        files_rel = [p.relative_to(input_path).as_posix() for p in sorted(group)]
        report["detected_paper_candidates"].append({
            "candidate_id": key,
            "file_count": len(group),
            "extensions": dict(suffixes),
            "files": files_rel,
            "has_metadata": any(p.name == "metadata.json" for p in group),
            "has_overview": any(p.name == "overview.md" for p in group),
            "has_chunks": any(p.name == "chunks.jsonl" for p in group),
            "has_visuals": any(p.name == "visuals.jsonl" for p in group),
            "status_guess": "complete" if {"metadata.json", "overview.md", "chunks.jsonl", "visuals.jsonl"}.issubset({p.name for p in group}) else "partial",
        })
    titles = defaultdict(list)
    for candidate in report["detected_paper_candidates"]:
        titles[candidate["candidate_id"].lower()].append(candidate["candidate_id"])
    report["possible_duplicate_papers"] = [values for values in titles.values() if len(values) > 1]
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def render_source_audit_report(audit: dict[str, Any]) -> str:
    lines = [
        "# Chapter 3 Local Paper Drop Audit Report",
        "",
        f"Input path: `{audit['input_path']}`",
        f"Exists: {audit['exists']}",
        "",
        "## File Count by Extension",
    ]
    if audit.get("file_count_by_extension"):
        lines.extend(f"- `{ext}`: {count}" for ext, count in audit["file_count_by_extension"].items())
    else:
        lines.append("- none")
    lines.extend(["", "## Detected Paper Candidates"])
    candidates = audit.get("detected_paper_candidates", [])
    if candidates:
        for c in candidates:
            lines.append(f"- `{c['candidate_id']}`: {c['status_guess']}, {c['file_count']} files, extensions={c['extensions']}")
    else:
        lines.append("- none detected")
    lines.extend(["", "## Complete / Partial / Unknown"])
    lines.append(f"- complete: {sum(1 for c in candidates if c.get('status_guess') == 'complete')}")
    lines.append(f"- partial: {sum(1 for c in candidates if c.get('status_guess') == 'partial')}")
    lines.append(f"- unknown: {0 if audit.get('exists') else 1}")
    lines.extend(["", "## Possible Duplicate Papers"])
    duplicates = audit.get("possible_duplicate_papers", [])
    lines.extend([f"- {dup}" for dup in duplicates] or ["- none"])
    lines.extend(["", "## Files Ignored and Reason"])
    ignored = audit.get("ignored_files", [])
    lines.extend([f"- `{item['path']}`: {item['reason']}" for item in ignored[:200]] or ["- none"])
    if len(ignored) > 200:
        lines.append(f"- ... {len(ignored) - 200} more ignored files")
    lines.extend(["", "## Next Migration Plan"])
    if audit.get("exists"):
        lines.append("- Treat the input as source_drop/staging; copy or normalize into `data/papers/processed/<paper_id>/` without deleting originals.")
    else:
        lines.append("- Source drop path is absent; normalize the already existing `data/papers/processed` real corpus and preserve this audit record.")
    return "\n".join(lines) + "\n"


def normalize_existing_corpus(root: Path, *, input_path: Path | None = None, overwrite: bool = False, dry_run: bool = False, limit: int | None = None, paper_id: str | None = None) -> dict[str, Any]:
    repo_root = Path.cwd()
    processed_root = root / "processed"
    raw_root = root / "raw"
    reports_root = root / "quality_reports"
    processed_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    original_manifest = {row.get("paper_id"): row for row in load_jsonl(root / "manifest.jsonl") if row.get("paper_id")}
    dirs = [p for p in sorted(processed_root.iterdir()) if p.is_dir()]
    if paper_id:
        dirs = [p for p in dirs if p.name == paper_id]
    if limit:
        dirs = dirs[:limit]
    manifest_rows: list[dict[str, Any]] = []
    migration = {
        "migrated_paper_count": 0,
        "processed_paper_count": 0,
        "partial_paper_count": 0,
        "failed_paper_count": 0,
        "metadata_only_count": 0,
        "copied_pdfs": 0,
        "generated_overviews": 0,
        "generated_chunks": 0,
        "generated_visuals": 0,
        "warnings": [],
        "failures": [],
        "dry_run": dry_run,
    }
    for paper_dir in dirs:
        pid = paper_dir.name
        old_manifest = dict(original_manifest.get(pid, {}))
        old_meta = _read_json(paper_dir / "metadata.json")
        title = old_manifest.get("title") or _title_from_overview(paper_dir / "overview.md") or pid
        domains = _as_list(old_manifest.get("domains") or old_meta.get("domains"))
        method_tags = _as_list(old_manifest.get("method_tags") or old_meta.get("method_tags"))
        benchmarks = _as_list(old_manifest.get("benchmarks") or old_meta.get("benchmarks"))
        authors = _as_list(old_manifest.get("authors") or old_meta.get("authors"))
        local_pdf_path = _normalize_local_pdf_path(old_manifest.get("local_pdf_path"), root, pid)
        pdf_url = old_manifest.get("pdf_url") or old_manifest.get("verified_pdf_url") or old_manifest.get("possible_pdf_url")
        access_status = old_manifest.get("access_status") or "local_existing"
        if access_status not in {"local_existing", "open_access", "metadata_only", "unknown"}:
            access_status = "unknown"
        access_note = old_manifest.get("access_note") or "local file provided by user; open-access status not asserted"
        if access_status == "open_access" and not (old_manifest.get("verified_pdf_url") or "arxiv" in access_note.lower()):
            access_status = "local_existing"
            access_note = "local file provided by user; open-access status not asserted"
        chunks_path = paper_dir / "chunks.jsonl"
        visuals_path = paper_dir / "visuals.jsonl"
        overview_path = paper_dir / "overview.md"
        if not overview_path.exists():
            if not dry_run:
                overview_path.write_text(_default_overview(title, old_manifest, domains, method_tags, benchmarks), encoding="utf-8")
            migration["generated_overviews"] += 1
        else:
            _ensure_overview_template(overview_path, title, old_manifest, domains, method_tags, benchmarks, dry_run=dry_run)
        if not chunks_path.exists():
            if not dry_run:
                chunks_path.write_text("", encoding="utf-8")
            migration["generated_chunks"] += 1
        if not visuals_path.exists():
            if not dry_run:
                visuals_path.write_text("", encoding="utf-8")
            migration["generated_visuals"] += 1
        if chunks_path.exists() and not dry_run:
            _normalize_chunks(chunks_path, pid, title, domains, method_tags)
        if visuals_path.exists() and not dry_run:
            warnings = _normalize_visuals(visuals_path, pid, title, domains, method_tags, repo_root)
            migration["warnings"].extend([f"{pid}: {w}" for w in warnings])
        chunk_count = count_jsonl(chunks_path)
        visual_count = count_jsonl(visuals_path)
        if not dry_run:
            metadata = PaperMetadata(
                paper_id=pid,
                title=title,
                authors=authors,
                year=old_manifest.get("year") or old_meta.get("year"),
                venue=old_manifest.get("venue") or old_meta.get("venue"),
                url=old_manifest.get("url") or old_meta.get("url"),
                pdf_url=pdf_url,
                arxiv_id=old_manifest.get("arxiv_id") or old_meta.get("arxiv_id"),
                doi=old_manifest.get("doi") or old_meta.get("doi"),
                domains=domains,
                method_tags=method_tags,
                benchmarks=benchmarks,
                source_input_path=to_posix_repo_path(str(input_path), repo_root) if input_path else old_manifest.get("source_input_path"),
                local_pdf_path=local_pdf_path,
                access_status=access_status,
                access_note=access_note,
                language=old_meta.get("language", "en"),
                processing={
                    "text_extracted": (paper_dir / "fulltext.txt").exists() or chunk_count > 0,
                    "overview_generated": overview_path.exists(),
                    "chunks_generated": chunk_count > 0,
                    "visuals_generated": visuals_path.exists(),
                    "figure_assets_extracted": (paper_dir / "figures").exists(),
                    "table_assets_extracted": (paper_dir / "tables").exists(),
                },
                quality={
                    "metadata_complete": bool(title),
                    "overview_complete": overview_path.exists(),
                    "chunk_count": chunk_count,
                    "visual_count": visual_count,
                    "warnings": [],
                },
                extraction={k: v for k, v in old_meta.items() if k not in {"paper_id", "title", "authors", "year", "venue", "url", "pdf_url", "arxiv_id", "domains", "method_tags", "benchmarks"}},
            )
            (paper_dir / "metadata.json").write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
        processing_status = "processed" if chunk_count > 0 and overview_path.exists() else "partial"
        row = PaperManifestEntry(
            paper_id=pid,
            title=title,
            authors=authors,
            year=old_manifest.get("year") or old_meta.get("year"),
            venue=old_manifest.get("venue") or old_meta.get("venue"),
            url=old_manifest.get("url") or old_meta.get("url"),
            pdf_url=pdf_url,
            arxiv_id=old_manifest.get("arxiv_id") or old_meta.get("arxiv_id"),
            domains=domains,
            method_tags=method_tags,
            benchmarks=benchmarks,
            access_status=access_status,
            access_note=access_note,
            source_input_path=to_posix_repo_path(str(input_path), repo_root) if input_path else old_manifest.get("source_input_path"),
            local_pdf_path=local_pdf_path,
            processed_dir=f"data/papers/processed/{pid}",
            processing_status=processing_status,
            has_overview=overview_path.exists(),
            has_chunks=chunk_count > 0,
            has_visuals=visual_count > 0,
            chunk_count=chunk_count,
            visual_count=visual_count,
            created_at=old_manifest.get("created_at") or old_manifest.get("downloaded_at") or now_iso(),
            updated_at=now_iso(),
            metadata={"legacy_manifest_fields": {k: v for k, v in old_manifest.items() if k not in PaperManifestEntry.model_fields}},
        ).model_dump(mode="json")
        manifest_rows.append(row)
        migration["migrated_paper_count"] += 1
        if processing_status == "processed":
            migration["processed_paper_count"] += 1
        else:
            migration["partial_paper_count"] += 1
    if not dry_run:
        # Preserve manifest rows outside processed dirs if any, but avoid duplicates.
        selected = {row["paper_id"] for row in manifest_rows}
        for pid, row in original_manifest.items():
            if pid not in selected and (not paper_id):
                try:
                    manifest_rows.append(PaperManifestEntry.model_validate({**row, "processing_status": row.get("processing_status", "metadata_only")}).model_dump(mode="json"))
                except Exception:
                    pass
        write_jsonl(root / "manifest.jsonl", sorted(manifest_rows, key=lambda r: r["paper_id"]))
    return migration


def render_migration_report(migration: dict[str, Any]) -> str:
    lines = ["# Chapter 3 Paper Corpus Migration Report", ""]
    for key in ["migrated_paper_count", "processed_paper_count", "partial_paper_count", "failed_paper_count", "metadata_only_count", "copied_pdfs", "generated_overviews", "generated_chunks", "generated_visuals"]:
        lines.append(f"- {key}: {migration.get(key, 0)}")
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {w}" for w in migration.get("warnings", [])[:500]] or ["- none"])
    lines.extend(["", "## Failures and Reasons"])
    lines.extend([f"- {f}" for f in migration.get("failures", [])] or ["- none"])
    return "\n".join(lines) + "\n"


def corpus_statistics(root: Path) -> dict[str, Any]:
    rows = load_jsonl(root / "manifest.jsonl")
    domains = Counter()
    method_tags = Counter()
    access = Counter()
    missing = Counter()
    duplicate_titles = Counter(row.get("title", "").lower() for row in rows if row.get("title"))
    for row in rows:
        domains.update(row.get("domains", []))
        method_tags.update(row.get("method_tags", []))
        access.update([row.get("access_status", "unknown")])
        for field in ["title", "authors", "year", "venue", "url", "domains", "method_tags"]:
            if not row.get(field):
                missing[field] += 1
    return {
        "total_manifest_count": len(rows),
        "processed_count": sum(1 for r in rows if r.get("processing_status") in {"processed", "completed"}),
        "partial_count": sum(1 for r in rows if r.get("processing_status") == "partial"),
        "failed_count": sum(1 for r in rows if r.get("processing_status") == "failed"),
        "chunk_count_total": sum(int(r.get("chunk_count") or 0) for r in rows),
        "visual_count_total": sum(int(r.get("visual_count") or 0) for r in rows),
        "papers_with_figures": sum(1 for r in rows if int(r.get("visual_count") or 0) > 0),
        "papers_with_tables": sum(1 for p in (root / "processed").glob("*") if (p / "tables").exists()),
        "missing_field_statistics": dict(missing),
        "top_domains": domains.most_common(20),
        "top_method_tags": method_tags.most_common(20),
        "duplicate_title_warnings": [title for title, count in duplicate_titles.items() if count > 1],
        "access_status_distribution": dict(access),
    }


def render_corpus_report(stats: dict[str, Any]) -> str:
    lines = ["# Chapter 3 Paper Corpus Report", ""]
    for key in ["total_manifest_count", "processed_count", "partial_count", "failed_count", "chunk_count_total", "visual_count_total", "papers_with_figures", "papers_with_tables"]:
        lines.append(f"- {key}: {stats.get(key)}")
    lines.extend(["", "## Missing Field Statistics"])
    lines.extend([f"- {k}: {v}" for k, v in stats.get("missing_field_statistics", {}).items()] or ["- none"])
    lines.extend(["", "## Top Domains"])
    lines.extend([f"- {k}: {v}" for k, v in stats.get("top_domains", [])] or ["- none"])
    lines.extend(["", "## Top Method Tags"])
    lines.extend([f"- {k}: {v}" for k, v in stats.get("top_method_tags", [])] or ["- none"])
    lines.extend(["", "## Duplicate Title Warnings"])
    lines.extend([f"- {t}" for t in stats.get("duplicate_title_warnings", [])] or ["- none"])
    lines.extend(["", "## Access Status Distribution"])
    lines.extend([f"- {k}: {v}" for k, v in stats.get("access_status_distribution", {}).items()] or ["- none"])
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        if not value.strip():
            return []
        return [x.strip() for x in re.split(r"[,;]", value) if x.strip()]
    return [value]


def _title_from_overview(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _normalize_local_pdf_path(value: str | None, root: Path, pid: str) -> str | None:
    candidate = root / "raw" / f"{pid}.pdf"
    if candidate.exists():
        return candidate.as_posix()
    return to_posix_repo_path(value, Path.cwd())


def _default_overview(title: str, manifest: dict[str, Any], domains: list[str], method_tags: list[str], benchmarks: list[str]) -> str:
    return f"""# {title}

YEAR: {manifest.get('year') or 'Unknown from available local files.'}
VENUE: {manifest.get('venue') or 'Unknown from available local files.'}
URL: {manifest.get('url') or 'Unknown from available local files.'}
PDF_URL: {manifest.get('pdf_url') or manifest.get('verified_pdf_url') or 'Unknown from available local files.'}
ARXIV_ID: {manifest.get('arxiv_id') or 'Unknown from available local files.'}
DOMAIN: {', '.join(domains) if domains else 'Unknown from available local files.'}
METHOD_TAGS: {', '.join(method_tags) if method_tags else 'Unknown from available local files.'}
BENCHMARKS: {', '.join(benchmarks) if benchmarks else 'Unknown from available local files.'}

## One Sentence Summary

Unknown from available local files.

## Why It Matters

Unknown from available local files.

## Core Idea

Unknown from available local files.

## Method

Unknown from available local files.

## Experiments

Unknown from available local files.

## Limitations

Unknown from available local files.

## Useful For These Questions

- Questions about {title}.

## Key Figures

None extracted.

## Key Tables

None extracted.
"""


def _ensure_overview_template(path: Path, title: str, manifest: dict[str, Any], domains: list[str], method_tags: list[str], benchmarks: list[str], *, dry_run: bool) -> None:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else _default_overview(title, manifest, domains, method_tags, benchmarks)
    changed = False
    if not text.startswith("# "):
        text = f"# {title}\n\n" + text
        changed = True
    for heading in OVERVIEW_HEADINGS:
        if heading not in text:
            text += f"\n{heading}\n\nUnknown from available local files.\n"
            changed = True
    if changed and not dry_run:
        path.write_text(text, encoding="utf-8")


def _normalize_chunks(path: Path, pid: str, title: str, domains: list[str], method_tags: list[str]) -> None:
    rows = load_jsonl(path)
    out = []
    for idx, row in enumerate(rows, 1):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        cid = row.get("chunk_id") or f"{pid}_chunk_{idx:04d}"
        metadata = dict(row.get("metadata") or {})
        metadata.update({
            "source_type": "paper_chunk",
            "domains": domains,
            "method_tags": method_tags,
            "source_domain": "paper_corpus",
            "evidence_role": "paper_claim",
            "contains_figure_reference": bool(re.search(r"\b(fig(?:ure)?\.?|图)\s*\d+", text, re.I)),
            "contains_table_reference": bool(re.search(r"\b(table|表)\s*\d+", text, re.I)),
        })
        row.update({
            "chunk_id": cid,
            "paper_id": pid,
            "source_id": row.get("source_id") or cid,
            "title": row.get("title") or title,
            "section": row.get("section") or row.get("section_title") or "Unknown",
            "page_start": int(row.get("page_start") or row.get("page") or 1),
            "page_end": int(row.get("page_end") or row.get("page_start") or row.get("page") or 1),
            "text": text,
            "token_count": int(row.get("token_count") or max(1, len(text) // 4)),
            "domains": domains,
            "method_tags": method_tags,
            "source_domain": "paper_corpus",
            "evidence_role": "paper_claim",
            "metadata": metadata,
        })
        out.append(row)
    write_jsonl(path, out)


def _normalize_visuals(path: Path, pid: str, title: str, domains: list[str], method_tags: list[str], repo_root: Path) -> list[str]:
    rows = load_jsonl(path)
    warnings = []
    out = []
    for idx, row in enumerate(rows, 1):
        vid = row.get("visual_id") or f"{pid}_vis_{idx:04d}"
        visual_type = row.get("visual_type") or "figure"
        if visual_type == "page":
            source_type = "paper_visual"
            evidence_role = "visual_support"
        elif visual_type == "table":
            source_type = "paper_table"
            evidence_role = "visual_support"
        else:
            source_type = "paper_figure"
            evidence_role = "visual_support"
        image_path = to_posix_repo_path(row.get("image_path"), repo_root)
        thumbnail_path = to_posix_repo_path(row.get("thumbnail_path"), repo_root)
        if image_path and not (repo_root / image_path).exists():
            warnings.append(f"image_path missing for {vid}: {image_path}; setting to null")
            image_path = None
        if thumbnail_path and not (repo_root / thumbnail_path).exists():
            warnings.append(f"thumbnail_path missing for {vid}: {thumbnail_path}; setting to null")
            thumbnail_path = None
        caption = str(row.get("caption") or row.get("title") or "").strip()
        if not caption:
            warnings.append(f"empty caption visual skipped: {vid}")
            continue
        metadata = dict(row.get("metadata") or {})
        metadata.update({"source_type": source_type, "domains": domains, "method_tags": method_tags, "source_domain": "paper_visuals", "evidence_role": evidence_role})
        row.update({
            "visual_id": vid,
            "paper_id": pid,
            "source_id": row.get("source_id") or vid,
            "visual_type": visual_type,
            "label": row.get("label") or row.get("title") or f"{visual_type.title()} {idx}",
            "title": row.get("title") or row.get("label") or f"{visual_type.title()} {idx}",
            "caption": caption,
            "page": row.get("page"),
            "section": row.get("section") or "Unknown",
            "image_path": image_path,
            "thumbnail_path": thumbnail_path,
            "nearby_text": row.get("nearby_text"),
            "ocr_text": row.get("ocr_text"),
            "visual_summary": row.get("visual_summary") or caption[:300],
            "bbox": row.get("bbox"),
            "source_domain": "paper_visuals",
            "evidence_role": evidence_role,
            "metadata": metadata,
        })
        out.append(row)
    write_jsonl(path, out)
    return warnings
