"""Fix fixture corpus paths after copying from main processed directory."""
import json
import shutil
from pathlib import Path

SRC = Path("C:/Users/brainclos_032/Desktop/AgentLadder/data/papers")
FIX = SRC / "fixtures"

# Copy raw PDFs to fixture
(FIX / "raw").mkdir(parents=True, exist_ok=True)
pdf_map = [("paper_001", "paper_react"), ("paper_012", "paper_self_rag"), ("paper_027", "paper_world_model")]
for pid_src, pid_fix in pdf_map:
    src_pdf = SRC / "raw" / f"{pid_src}.pdf"
    dst_pdf = FIX / "raw" / f"{pid_fix}.pdf"
    if src_pdf.exists() and not dst_pdf.exists():
        shutil.copy2(str(src_pdf), str(dst_pdf))
        print(f"Copied PDF: {pid_src} -> {pid_fix}")

# Fix image_path in visuals to use fixture-relative paths
replacements = [
    ("data/papers/processed/paper_react/", "data/papers/fixtures/processed/paper_react/"),
    ("data/papers/processed/paper_self_rag/", "data/papers/fixtures/processed/paper_self_rag/"),
    ("data/papers/processed/paper_world_model/", "data/papers/fixtures/processed/paper_world_model/"),
    ("data/papers/processed/paper_001/", "data/papers/fixtures/processed/paper_react/"),
    ("data/papers/processed/paper_012/", "data/papers/fixtures/processed/paper_self_rag/"),
    ("data/papers/processed/paper_027/", "data/papers/fixtures/processed/paper_world_model/"),
]

for fid in ["paper_react", "paper_self_rag", "paper_world_model"]:
    vf = FIX / "processed" / fid / "visuals.jsonl"
    if not vf.exists():
        continue
    visuals = []
    with open(vf, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                v = json.loads(line)
                img = v.get("image_path", "")
                for old, new in replacements:
                    img = img.replace(old, new)
                v["image_path"] = img.replace("\\", "/")
                visuals.append(v)
    with open(vf, "w", encoding="utf-8") as f:
        for v in visuals:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    print(f"{fid}: {len(visuals)} visuals, paths fixed")

# Update manifest
mfs = []
with open(FIX / "manifest.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            mfs.append(json.loads(line))

for m in mfs:
    m["local_pdf_path"] = f"data/papers/fixtures/raw/{m['paper_id']}.pdf"

with open(FIX / "manifest.jsonl", "w", encoding="utf-8") as f:
    for m in mfs:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")

print("All paths fixed.")
