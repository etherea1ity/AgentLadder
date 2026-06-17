"""Download arXiv PDFs and generate processed corpus for all candidates.

Phase F-G: Download + Extract + Generate metadata/overview/chunks/visuals.
Uses pymupdf for PDF extraction when MinerU is not available.
Idempotent: skips already-processed papers.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from datetime import UTC, datetime
from collections import Counter

try:
    import fitz  # pymupdf
    HAVE_FITZ = True
except ImportError:
    HAVE_FITZ = False

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

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


def now_iso():
    return datetime.now(UTC).isoformat()


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def download_pdf(arxiv_id: str, dest: Path) -> bool:
    """Download PDF from arXiv. Returns True on success."""
    if dest.exists():
        print(f"  PDF already exists: {dest.name}")
        return True
    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AgentLadder/0.3 (research corpus builder; contact@example.com)"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        print(f"  Downloaded: {dest.name} ({dest.stat().st_size} bytes)")
        return True
    except Exception as e:
        print(f"  Download FAILED: {arxiv_id} — {e}")
        return False


def extract_text_pymupdf(pdf_path: Path) -> dict:
    """Extract text and sections from PDF using pymupdf."""
    doc = fitz.open(str(pdf_path))
    fulltext_parts = []
    sections = []
    current_section = {"section": "Introduction", "page_start": 1, "page_end": 1, "text": ""}

    for page_num, page in enumerate(doc, 1):
        text = page.get_text("text") or ""
        fulltext_parts.append(text)

        # Try to detect section breaks
        for line in text.split("\n"):
            line = line.strip()
            if re.match(r"^(?:\d+\.?\s+)?(?:Abstract|Introduction|Related Work|Background|Method|Approach|Experiment|Evaluation|Result|Discussion|Conclusion|Limitation|Future Work|Reference|Appendix|Acknowledgment)", line, re.I):
                if current_section["text"].strip():
                    sections.append(current_section)
                current_section = {"section": line[:80], "page_start": page_num, "page_end": page_num, "text": ""}
        current_section["text"] += text + "\n"
        current_section["page_end"] = page_num

    if current_section["text"].strip():
        sections.append(current_section)

    try:
        total_pages = doc.page_count
    except:
        total_pages = len(fulltext_parts)

    doc.close()
    fulltext = "\n".join(fulltext_parts)

    return {
        "fulltext": fulltext,
        "total_pages": total_pages,
        "total_chars": len(fulltext),
        "total_words": len(fulltext.split()),
        "sections": sections,
        "sections_found": len(sections),
    }


def extract_figures_tables(pdf_path: Path, paper_dir: Path, paper_id: str) -> tuple[list[dict], int, int]:
    """Extract figures and tables from PDF pages as images. Returns (visuals, fig_count, table_count)."""
    visuals = []
    fig_count = 0
    table_count = 0

    if not HAVE_FITZ:
        return visuals, fig_count, table_count

    figures_dir = paper_dir / "figures"
    tables_dir = paper_dir / "tables"
    pages_dir = paper_dir / "pages"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = fitz.open(str(pdf_path))
        for page_num, page in enumerate(doc, 1):
            # Extract page as image (for thumbnails)
            try:
                pix = page.get_pixmap(dpi=150)
                page_img = pages_dir / f"page_{page_num:04d}.png"
                if not page_img.exists():
                    pix.save(str(page_img))
            except:
                pass

            # Get page text for caption detection
            text = page.get_text("text") or ""

            # Detect figure/table references in page text
            fig_matches = re.findall(r"(Figure\s*\d+[.:]\s*[^\n]{10,200})", text, re.I)
            table_matches = re.findall(r"(Table\s*\d+[.:]\s*[^\n]{10,200})", text, re.I)

            for i, match in enumerate(fig_matches):
                vid = f"{paper_id}_fig_{fig_count + 1:04d}"
                # Save figure image (page region or full page as fallback)
                img_path = figures_dir / f"fig_{page_num:04d}_{i:02d}.png"
                if not img_path.exists():
                    try:
                        pix = page.get_pixmap(dpi=150)
                        pix.save(str(img_path))
                    except:
                        img_path = None
                if img_path:
                    visuals.append({
                        "visual_id": vid,
                        "paper_id": paper_id,
                        "source_id": vid,
                        "visual_type": "figure",
                        "title": re.match(r"Figure\s*\d+", match, re.I).group(0) if re.match(r"Figure\s*\d+", match, re.I) else f"Figure {fig_count + 1}",
                        "caption": match[:300],
                        "page": page_num,
                        "section": "Unknown",
                        "image_path": str(img_path.relative_to(img_path.parent.parent.parent.parent)).replace("\\", "/"),
                        "thumbnail_path": None,
                        "nearby_text": text[max(0, text.find(match) - 200):text.find(match) + len(match) + 200][:500],
                        "ocr_text": None,
                        "visual_summary": match[:300],
                        "bbox": None,
                        "metadata": {
                            "source_type": "paper_figure",
                            "domains": [],
                            "method_tags": [],
                            "source_domain": "paper_visuals",
                            "evidence_role": "visual_support",
                        },
                    })
                fig_count += 1

            for i, match in enumerate(table_matches):
                vid = f"{paper_id}_tab_{table_count + 1:04d}"
                visuals.append({
                    "visual_id": vid,
                    "paper_id": paper_id,
                    "source_id": vid,
                    "visual_type": "table",
                    "title": re.match(r"Table\s*\d+", match, re.I).group(0) if re.match(r"Table\s*\d+", match, re.I) else f"Table {table_count + 1}",
                    "caption": match[:300],
                    "page": page_num,
                    "section": "Unknown",
                    "image_path": None,
                    "thumbnail_path": None,
                    "nearby_text": text[max(0, text.find(match) - 200):text.find(match) + len(match) + 200][:500],
                    "ocr_text": None,
                    "visual_summary": match[:300],
                    "bbox": None,
                    "metadata": {
                        "source_type": "paper_table",
                        "domains": [],
                        "method_tags": [],
                        "source_domain": "paper_visuals",
                        "evidence_role": "visual_support",
                    },
                })
                table_count += 1

        doc.close()
    except Exception as e:
        print(f"  Visual extraction warning: {e}")

    return visuals, fig_count, table_count


def generate_chunks(fulltext: str, sections: list[dict], paper_id: str, domains: list[str], method_tags: list[str]) -> list[dict]:
    """Split fulltext into chunks with overlap."""
    chunks = []
    chunk_idx = 0
    target_size = 800  # chars (~600-900 tokens)
    overlap = 120

    # Use sections if available, otherwise split raw text
    sources = sections if sections else [{"section": "Full Text", "page_start": 1, "page_end": 1, "text": fulltext}]

    for section in sources:
        text = section.get("text", "").strip()
        if not text:
            continue
        section_name = section.get("section", "Unknown")
        page_start = section.get("page_start", 1)
        page_end = section.get("page_end", 1)

        start = 0
        while start < len(text):
            end = min(start + target_size, len(text))
            chunk_text = text[start:end].strip()
            if not chunk_text:
                start = end
                continue

            chunk_idx += 1
            cid = f"{paper_id}_chunk_{chunk_idx:04d}"
            tokens_est = max(1, len(chunk_text) // 4)

            chunks.append({
                "chunk_id": cid,
                "paper_id": paper_id,
                "source_id": cid,
                "section": section_name[:100],
                "page_start": page_start,
                "page_end": page_end,
                "text": chunk_text,
                "token_count": tokens_est,
                "metadata": {
                    "source_type": "paper_chunk",
                    "domains": domains,
                    "method_tags": method_tags,
                    "source_domain": "paper_corpus",
                    "evidence_role": "paper_claim",
                    "contains_figure_reference": bool(re.search(r"\b(fig(?:ure)?\.?)\s*\d+", chunk_text, re.I)),
                    "contains_table_reference": bool(re.search(r"\b(table)\s*\d+", chunk_text, re.I)),
                },
            })

            start = end - overlap  # overlap
            if start >= len(text):
                break

    return chunks


def generate_metadata(candidate: dict, processed_dir: Path, has_chunks: bool, has_visuals: bool, chunk_count: int, visual_count: int) -> dict:
    """Generate metadata.json from candidate manifest data."""
    return {
        "paper_id": candidate["paper_id"],
        "title": candidate["title"],
        "authors": candidate.get("authors", []),
        "year": candidate.get("year"),
        "venue": candidate.get("venue"),
        "url": candidate.get("url"),
        "pdf_url": candidate.get("verified_pdf_url") or candidate.get("possible_pdf_url"),
        "arxiv_id": candidate.get("arxiv_id"),
        "doi": None,
        "domains": candidate.get("domains", []),
        "method_tags": candidate.get("method_tags", []),
        "benchmarks": [],
        "source_input_path": "data/papers/manifest_candidates_expanded.jsonl",
        "local_pdf_path": f"data/papers/raw/{candidate['paper_id']}.pdf",
        "access_status": candidate.get("access_status", "open_access"),
        "access_note": candidate.get("access_note", ""),
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
            "warnings": [],
        },
    }


def generate_overview(candidate: dict) -> str:
    """Generate overview.md from candidate manifest data."""
    title = candidate["title"]
    year = candidate.get("year", "Unknown from available local files.")
    venue = candidate.get("venue", "Unknown from available local files.")
    url = candidate.get("url", "Unknown from available local files.")
    pdf = candidate.get("verified_pdf_url") or candidate.get("possible_pdf_url") or "Unknown"
    arxiv = candidate.get("arxiv_id", "Unknown from available local files.")
    domains = ", ".join(candidate.get("domains", [])) or "Unknown from available local files."
    tags = ", ".join(candidate.get("method_tags", [])) or "Unknown from available local files."
    why = candidate.get("why_included", "")
    tier = candidate.get("tier", "")

    return f"""# {title}

YEAR: {year}
VENUE: {venue}
URL: {url}
PDF_URL: {pdf}
ARXIV_ID: {arxiv}
DOMAIN: {domains}
METHOD_TAGS: {tags}
BENCHMARKS: Unknown from available local files.

## One Sentence Summary

{title} ({year}) — {why}.

## Why It Matters

This paper is a {tier}-tier reference in the AI Research Agent literature corpus.
{why}.

## Core Idea

Unknown from available local files. Full extraction requires PDF processing.

## Method

Unknown from available local files. Full extraction requires PDF processing.

## Experiments

Unknown from available local files. Full extraction requires PDF processing.

## Limitations

Unknown from available local files.

## Useful For These Questions

- What is {title}?
- How does {title.split(':')[0].strip()} work?
- Compare {title.split(':')[0].strip()} with related methods.

## Key Figures

None extracted.

## Key Tables

None extracted.
"""


def process_candidates(root: Path, limit: int = None, skip_download: bool = False, dry_run: bool = False):
    """Main processing pipeline."""
    candidates = load_jsonl(root / "manifest_candidates_expanded.jsonl")
    if limit:
        candidates = candidates[:limit]

    processed_root = root / "processed"
    raw_root = root / "raw"
    processed_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    stats = {
        "downloaded": 0,
        "download_failed": 0,
        "text_extracted": 0,
        "chunks_generated": 0,
        "visuals_extracted": 0,
        "skipped": 0,
        "total": len(candidates),
    }

    new_manifest_rows = []

    for i, candidate in enumerate(candidates):
        pid = candidate["paper_id"]
        title = candidate["title"][:80]
        level = candidate.get("processing_level", "full_pdf")
        arxiv_id = candidate.get("arxiv_id")
        domains = candidate.get("domains", [])
        method_tags = candidate.get("method_tags", [])

        paper_dir = processed_root / pid
        pdf_path = raw_root / f"{pid}.pdf"

        print(f"\n[{i+1}/{len(candidates)}] {pid}: {title[:60]}")
        print(f"  Level: {level}, Tier: {candidate.get('tier')}, arXiv: {arxiv_id}")

        # Skip if already processed
        if (paper_dir / "metadata.json").exists() and (paper_dir / "overview.md").exists():
            print(f"  SKIP: Already processed")
            stats["skipped"] += 1
            continue

        if dry_run:
            print(f"  DRY RUN: Would process")
            continue

        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "figures").mkdir(exist_ok=True)
        (paper_dir / "tables").mkdir(exist_ok=True)
        (paper_dir / "pages").mkdir(exist_ok=True)

        has_pdf = False
        has_chunks = False
        has_visuals = False
        chunk_count = 0
        visual_count = 0

        # Step 1: Download PDF for full_pdf papers
        if level == "full_pdf" and arxiv_id and not skip_download:
            has_pdf = download_pdf(arxiv_id, pdf_path)
            if has_pdf:
                stats["downloaded"] += 1
            else:
                stats["download_failed"] += 1
        elif pdf_path.exists():
            has_pdf = True

        # Step 2: Extract text if PDF available
        if has_pdf and level in ("full_pdf",):
            try:
                extracted = extract_text_pymupdf(pdf_path)
                (paper_dir / "fulltext.txt").write_text(extracted["fulltext"], encoding="utf-8")

                # Write sections.json
                sections_data = {
                    "paper_id": pid,
                    "total_pages": extracted["total_pages"],
                    "total_chars": extracted["total_chars"],
                    "total_words": extracted["total_words"],
                    "sections_found": extracted["sections_found"],
                    "sections": extracted["sections"],
                    "extraction_method": "pymupdf",
                }
                (paper_dir / "sections.json").write_text(json.dumps(sections_data, ensure_ascii=False, indent=2), encoding="utf-8")

                # Generate chunks
                chunks = generate_chunks(extracted["fulltext"], extracted["sections"], pid, domains, method_tags)
                write_jsonl(paper_dir / "chunks.jsonl", chunks)
                has_chunks = True
                chunk_count = len(chunks)
                stats["chunks_generated"] += 1
                stats["text_extracted"] += 1

                # Extract figures/tables
                visuals, fig_count, table_count = extract_figures_tables(pdf_path, paper_dir, pid)
                write_jsonl(paper_dir / "visuals.jsonl", visuals)
                has_visuals = len(visuals) > 0
                visual_count = len(visuals)
                if visuals:
                    stats["visuals_extracted"] += 1

                print(f"  Extracted: {extracted['total_chars']} chars, {chunk_count} chunks, {visual_count} visuals")
            except Exception as e:
                print(f"  Extraction FAILED: {e}")
                (paper_dir / "chunks.jsonl").write_text("", encoding="utf-8")
                (paper_dir / "visuals.jsonl").write_text("", encoding="utf-8")
        else:
            (paper_dir / "chunks.jsonl").write_text("", encoding="utf-8")
            (paper_dir / "visuals.jsonl").write_text("", encoding="utf-8")

        # Step 3: Generate metadata.json
        metadata = generate_metadata(candidate, paper_dir, has_chunks, has_visuals, chunk_count, visual_count)
        (paper_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        # Step 4: Generate overview.md
        overview = generate_overview(candidate)
        (paper_dir / "overview.md").write_text(overview, encoding="utf-8")

        # Build manifest row
        processing_status = "processed" if has_chunks else "partial"
        new_manifest_rows.append({
            "paper_id": pid,
            "title": candidate["title"],
            "authors": candidate.get("authors", []),
            "year": candidate.get("year"),
            "venue": candidate.get("venue"),
            "url": candidate.get("url"),
            "pdf_url": candidate.get("verified_pdf_url") or candidate.get("possible_pdf_url"),
            "arxiv_id": arxiv_id,
            "domains": domains,
            "method_tags": method_tags,
            "benchmarks": [],
            "access_status": candidate.get("access_status", "open_access"),
            "access_note": candidate.get("access_note", ""),
            "source_input_path": "data/papers/manifest_candidates_expanded.jsonl",
            "local_pdf_path": f"data/papers/raw/{pid}.pdf" if has_pdf else None,
            "processed_dir": f"data/papers/processed/{pid}",
            "processing_status": processing_status,
            "has_overview": True,
            "has_chunks": has_chunks,
            "has_visuals": has_visuals,
            "chunk_count": chunk_count,
            "visual_count": visual_count,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })

        # Be nice to arXiv
        if has_pdf:
            time.sleep(0.3)

    # Update manifest.jsonl — append new entries, don't overwrite existing
    if not dry_run and new_manifest_rows:
        existing_manifest = load_jsonl(root / "manifest.jsonl")
        existing_ids = {r["paper_id"] for r in existing_manifest}
        updated = [r for r in existing_manifest]  # keep all existing
        for row in new_manifest_rows:
            if row["paper_id"] not in existing_ids:
                updated.append(row)
        write_jsonl(root / "manifest.jsonl", sorted(updated, key=lambda r: r["paper_id"]))
        print(f"\nManifest updated: {len(updated)} total entries ({len(new_manifest_rows)} new)")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Download and process paper candidates")
    parser.add_argument("--root", default="data/papers")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    stats = process_candidates(root, limit=args.limit, skip_download=args.skip_download, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"Processing complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
