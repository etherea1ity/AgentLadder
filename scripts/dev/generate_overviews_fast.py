"""Generate metadata.json + overview.md for ALL candidates FAST (no PDF extraction)."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import UTC, datetime

def now_iso():
    return datetime.now(UTC).isoformat()

def main():
    root = Path("data/papers")
    candidates_path = root / "manifest_candidates_expanded.jsonl"

    candidates = []
    with open(candidates_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                candidates.append(json.loads(line))

    processed_root = root / "processed"
    processed_root.mkdir(parents=True, exist_ok=True)

    new_manifest = []
    stats = {"overview_only": 0, "metadata_only": 0, "full_pdf_partial": 0}

    for c in candidates:
        pid = c["paper_id"]
        title = c["title"]
        year = c.get("year", "Unknown")
        venue = c.get("venue", "Unknown")
        url = c.get("url", "Unknown")
        pdf_url = c.get("verified_pdf_url") or c.get("possible_pdf_url") or "Unknown"
        arxiv = c.get("arxiv_id", "Unknown")
        domains = c.get("domains", [])
        tags = c.get("method_tags", [])
        why = c.get("why_included", "")
        tier = c.get("tier", "")
        level = c.get("processing_level", "full_pdf")

        paper_dir = processed_root / pid
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "figures").mkdir(exist_ok=True)
        (paper_dir / "tables").mkdir(exist_ok=True)
        (paper_dir / "pages").mkdir(exist_ok=True)

        # Skip if already fully processed (has chunks)
        chunks_path = paper_dir / "chunks.jsonl"
        if chunks_path.exists() and chunks_path.stat().st_size > 0:
            stats["full_pdf_partial"] += 0  # already done
            continue

        has_chunks = False
        chunk_count = 0
        has_visuals = False
        visual_count = 0

        if level == "metadata_only":
            processing_status = "metadata_only"
            stats["metadata_only"] += 1
        elif level == "overview_only":
            processing_status = "partial"
            stats["overview_only"] += 1
        else:
            processing_status = "partial"
            stats["full_pdf_partial"] += 1

        # metadata.json
        metadata = {
            "paper_id": pid,
            "title": title,
            "authors": c.get("authors", []),
            "year": year,
            "venue": venue,
            "url": url,
            "pdf_url": pdf_url,
            "arxiv_id": arxiv,
            "doi": None,
            "domains": domains,
            "method_tags": tags,
            "benchmarks": [],
            "source_input_path": "data/papers/manifest_candidates_expanded.jsonl",
            "local_pdf_path": f"data/papers/raw/{pid}.pdf",
            "access_status": c.get("access_status", "open_access"),
            "access_note": c.get("access_note", ""),
            "language": "en",
            "processing": {
                "text_extracted": has_chunks,
                "overview_generated": True,
                "chunks_generated": has_chunks,
                "visuals_generated": has_visuals,
                "figure_assets_extracted": False,
                "table_assets_extracted": False,
            },
            "quality": {
                "metadata_complete": True,
                "overview_complete": True,
                "chunk_count": chunk_count,
                "visual_count": visual_count,
                "warnings": ["PDF extraction pending; chunks and visuals not yet generated"] if level == "full_pdf" and not has_chunks else [],
            },
        }
        (paper_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        # overview.md
        overview = f"""# {title}

YEAR: {year}
VENUE: {venue}
URL: {url}
PDF_URL: {pdf_url}
ARXIV_ID: {arxiv}
DOMAIN: {", ".join(domains) if domains else "Unknown from available local files."}
METHOD_TAGS: {", ".join(tags) if tags else "Unknown from available local files."}
BENCHMARKS: Unknown from available local files.

## One Sentence Summary

{title} ({year}) — {why}.

## Why It Matters

This paper is a {tier}-tier reference in the AI Research Agent literature corpus. {why}

## Core Idea

PDF extraction pending. Overview will be updated after full processing.

## Method

PDF extraction pending. Overview will be updated after full processing.

## Experiments

Unknown from available local files.

## Limitations

Unknown from available local files.

## Useful For These Questions

- What is {title.split(":")[0].strip()}?
- How does {title.split(":")[0].strip()[:60]} work?
- Compare {title.split(":")[0].strip()[:40]} with related approaches.

## Key Figures

None extracted.

## Key Tables

None extracted.
"""
        (paper_dir / "overview.md").write_text(overview, encoding="utf-8")

        # Empty chunks/visuals if not exist
        if not chunks_path.exists():
            chunks_path.write_text("", encoding="utf-8")
        visuals_path = paper_dir / "visuals.jsonl"
        if not visuals_path.exists():
            visuals_path.write_text("", encoding="utf-8")

        new_manifest.append({
            "paper_id": pid,
            "title": title,
            "authors": c.get("authors", []),
            "year": year,
            "venue": venue,
            "url": url,
            "pdf_url": pdf_url,
            "arxiv_id": arxiv,
            "domains": domains,
            "method_tags": tags,
            "benchmarks": [],
            "access_status": c.get("access_status", "open_access"),
            "access_note": c.get("access_note", ""),
            "source_input_path": "data/papers/manifest_candidates_expanded.jsonl",
            "local_pdf_path": f"data/papers/raw/{pid}.pdf",
            "processed_dir": f"data/papers/processed/{pid}",
            "processing_status": processing_status,
            "has_overview": True,
            "has_chunks": has_chunks,
            "has_visuals": has_visuals,
            "chunk_count": chunk_count,
            "visual_count": visual_count,
            "tier": tier,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })

    # Update manifest
    existing = {}
    manifest_path = root / "manifest.jsonl"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    existing[r["paper_id"]] = r

    for row in new_manifest:
        if row["paper_id"] not in existing:
            existing[row["paper_id"]] = row

    all_rows = sorted(existing.values(), key=lambda r: r["paper_id"])
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Manifest: {len(all_rows)} total ({len(new_manifest)} new, {len(existing) - len(new_manifest)} existing)")
    print(f"Stats: {stats}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
