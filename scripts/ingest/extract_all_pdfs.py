"""Extract text from downloaded PDFs using pymupdf. Idempotent."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

try:
    import fitz
except ImportError:
    print("pymupdf not available")
    sys.exit(1)

def token_est(text: str) -> int:
    return max(1, len(text) // 4)

def extract_and_save(pdf_path: Path, paper_dir: Path, pid: str, domains: list, tags: list):
    """Extract text, chunks, and basic visuals from PDF."""
    if (paper_dir / "fulltext.txt").exists() and (paper_dir / "chunks.jsonl").exists() and (paper_dir / "chunks.jsonl").stat().st_size > 10:
        print(f"  SKIP: already extracted")
        return {"chunks": 0, "visuals": 0, "chars": 0}

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        print(f"  ERROR opening PDF: {e}")
        return {"chunks": 0, "visuals": 0, "chars": 0}

    total_pages = doc.page_count
    fulltext_parts = []
    sections = []
    curr = {"section": "Body", "page_start": 1, "page_end": 1, "text": ""}

    for pn in range(total_pages):
        try:
            text = doc[pn].get_text("text") or ""
        except:
            text = ""
        fulltext_parts.append(text)

        for line in text.split("\n"):
            line = line.strip()
            if re.match(r"^(?:\d+\.?\s+)?(?:Abstract|Introduction|Related Work|Background|Method|Approach|Experiment|Evaluation|Result|Discussion|Conclusion|Limitation|Future Work|Reference|Appendix|Acknowledgment)", line, re.I):
                if curr["text"].strip():
                    sections.append(curr)
                curr = {"section": line[:80], "page_start": pn+1, "page_end": pn+1, "text": ""}
        curr["text"] += text + "\n"
        curr["page_end"] = pn + 1
    if curr["text"].strip():
        sections.append(curr)

    doc.close()
    fulltext = "\n".join(fulltext_parts)

    # Save fulltext
    (paper_dir / "fulltext.txt").write_text(fulltext, encoding="utf-8")

    # Save sections.json
    (paper_dir / "sections.json").write_text(json.dumps({
        "paper_id": pid, "total_pages": total_pages,
        "total_chars": len(fulltext), "total_words": len(fulltext.split()),
        "sections_found": len(sections), "sections": sections,
        "extraction_method": "pymupdf"
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Generate chunks (simple overlap)
    chunks = []
    cidx = 0
    target = 800
    overlap = 120
    for sec in sections:
        text = sec["text"].strip()
        if not text:
            continue
        s = 0
        while s < len(text):
            e = min(s + target, len(text))
            ct = text[s:e].strip()
            if ct:
                cidx += 1
                cid = f"{pid}_chunk_{cidx:04d}"
                chunks.append({
                    "chunk_id": cid, "paper_id": pid, "source_id": cid,
                    "section": sec["section"][:100],
                    "page_start": sec["page_start"], "page_end": sec["page_end"],
                    "text": ct, "token_count": token_est(ct),
                    "metadata": {
                        "source_type": "paper_chunk", "domains": domains,
                        "method_tags": tags, "source_domain": "paper_corpus",
                        "evidence_role": "paper_claim",
                        "contains_figure_reference": bool(re.search(r"\bfig(?:ure)?\.?\s*\d+", ct, re.I)),
                        "contains_table_reference": bool(re.search(r"\btable\s*\d+", ct, re.I)),
                    },
                })
            s = e - overlap if e < len(text) else e + 1

    # Write chunks
    with open(paper_dir / "chunks.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for ch in chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    # Basic visuals from text (using already-extracted fulltext)
    visuals = []
    all_text = "\n".join(fulltext_parts)
    fig_refs = re.findall(r"(Figure\s*\d+[.:]\s*[^\n]{20,200})", all_text, re.I)
    tab_refs = re.findall(r"(Table\s*\d+[.:]\s*[^\n]{20,200})", all_text, re.I)

    for i, cap in enumerate(fig_refs):
        vid = f"{pid}_fig_{i+1:04d}"
        visuals.append({
            "visual_id": vid, "paper_id": pid, "source_id": vid,
            "visual_type": "figure",
            "title": re.match(r"Figure\s*\d+", cap, re.I).group(0) if re.match(r"Figure\s*\d+", cap, re.I) else f"Figure {i+1}",
            "caption": cap[:300], "page": 1, "section": "Unknown",
            "image_path": None, "thumbnail_path": None,
            "nearby_text": None, "ocr_text": None, "visual_summary": cap[:300],
            "bbox": None,
            "metadata": {"source_type": "paper_figure", "domains": domains,
                         "method_tags": tags, "source_domain": "paper_visuals",
                         "evidence_role": "visual_support"},
        })
    for i, cap in enumerate(tab_refs):
        vid = f"{pid}_tab_{i+1:04d}"
        visuals.append({
            "visual_id": vid, "paper_id": pid, "source_id": vid,
            "visual_type": "table",
            "title": re.match(r"Table\s*\d+", cap, re.I).group(0) if re.match(r"Table\s*\d+", cap, re.I) else f"Table {i+1}",
            "caption": cap[:300], "page": 1, "section": "Unknown",
            "image_path": None, "thumbnail_path": None,
            "nearby_text": None, "ocr_text": None, "visual_summary": cap[:300],
            "bbox": None,
            "metadata": {"source_type": "paper_table", "domains": domains,
                         "method_tags": tags, "source_domain": "paper_visuals",
                         "evidence_role": "visual_support"},
        })

    with open(paper_dir / "visuals.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for v in visuals:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")

    return {"chunks": len(chunks), "visuals": len(visuals), "chars": len(fulltext)}


def main():
    root = Path("data/papers")
    manifest_path = root / "manifest.jsonl"
    manifest = []
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                manifest.append(json.loads(line))

    # Extract for papers with PDF but no chunks
    todo = []
    for m in manifest:
        pid = m["paper_id"]
        pdf = root / "raw" / f"{pid}.pdf"
        chunks = root / "processed" / pid / "chunks.jsonl"
        if pdf.exists() and (not chunks.exists() or chunks.stat().st_size == 0):
            todo.append(m)

    print(f"Extracting text for {len(todo)} papers...")
    total_chunks = 0
    total_visuals = 0
    ok = 0
    fail = 0

    for i, m in enumerate(todo):
        pid = m["paper_id"]
        pdf = root / "raw" / f"{pid}.pdf"
        paper_dir = root / "processed" / pid
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "figures").mkdir(exist_ok=True)
        (paper_dir / "tables").mkdir(exist_ok=True)
        (paper_dir / "pages").mkdir(exist_ok=True)

        print(f"[{i+1}/{len(todo)}] {pid}: {m['title'][:60]}")

        try:
            result = extract_and_save(
                pdf, paper_dir, pid,
                m.get("domains", []), m.get("method_tags", [])
            )
            if result["chunks"] > 0:
                ok += 1
                total_chunks += result["chunks"]
                total_visuals += result["visuals"]
                print(f"  OK: {result['chunks']} chunks, {result['visuals']} visuals, {result['chars']} chars")
            else:
                fail += 1
                print(f"  WARN: no text extracted")
        except Exception as e:
            fail += 1
            print(f"  FAIL: {e}")

    # Update manifest processing status
    updated = []
    for m in manifest:
        chunks_path = root / "processed" / m["paper_id"] / "chunks.jsonl"
        if chunks_path.exists() and chunks_path.stat().st_size > 10:
            m["processing_status"] = "processed"
            m["has_chunks"] = True
            # Count chunks
            cc = 0
            with open(chunks_path, encoding="utf-8") as f:
                cc = sum(1 for line in f if line.strip())
            m["chunk_count"] = cc
        updated.append(m)

    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        for m in updated:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    print(f"\nDone: {ok} extracted, {fail} failed, {total_chunks} chunks, {total_visuals} visuals")
    print(f"Manifest updated")

if __name__ == "__main__":
    main()
