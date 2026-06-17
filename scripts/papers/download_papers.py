"""
下载 paper-index.yaml 中指定论文的 PDF 到对应分类目录。

用法:
    python scripts/papers/download_papers.py                    # 下载全部 to_download 的论文
    python scripts/papers/download_papers.py --dry-run          # 预览，不下载
    python scripts/papers/download_papers.py --category 01      # 只下载某个分类
    python scripts/papers/download_papers.py --tag core         # 只下载 core 论文
    python scripts/papers/download_papers.py --id paper-0101    # 下载指定论文
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAPERS_DIR = PROJECT_ROOT / "data" / "raw" / "papers"
INDEX_FILE = PAPERS_DIR / "paper-index.yaml"


def load_index() -> dict:
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def download_paper(paper: dict, dry_run: bool = False) -> bool:
    """下载单篇论文的 PDF。返回 True 表示成功。"""
    arxiv_id = paper.get("arxiv")
    if not arxiv_id:
        print(f"  [SKIP] {paper['id']}: 无 arxiv ID")
        return False

    category = paper["category"]
    target_dir = PAPERS_DIR / category
    pdf_path = target_dir / f"{paper['id']}.pdf"

    if pdf_path.exists():
        print(f"  [EXISTS] {paper['id']}: {pdf_path}")
        return True

    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    if dry_run:
        print(f"  [DRY-RUN] {paper['id']}: {url} -> {pdf_path}")
        return True

    print(f"  [DOWNLOAD] {paper['id']}: {arxiv_id} ({paper['title'][:60]}...)")
    try:
        subprocess.run(
            [
                "curl", "-L", "-o", str(pdf_path),
                "--retry", "3",
                "--connect-timeout", "30",
                "--max-time", "300",
                url,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)  # 礼貌间隔，避免被封
        return True
    except subprocess.CalledProcessError:
        print(f"  [FAIL] {paper['id']}: 下载失败")
        # 清理失败的文件
        if pdf_path.exists():
            pdf_path.unlink()
        return False


def main():
    parser = argparse.ArgumentParser(description="下载 Agent Ladder 论文 PDF")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--category", type=str, help="限定分类 (如 01, 02)")
    parser.add_argument("--tag", type=str, help="限定标签 (如 core, survey)")
    parser.add_argument("--id", type=str, help="指定论文 ID")
    args = parser.parse_args()

    index = load_index()
    papers = index["papers"]

    # 过滤
    if args.id:
        papers = [p for p in papers if p["id"] == args.id]
    if args.category:
        cat = f"0{args.category}-" if len(args.category) == 1 else f"{args.category}-"
        papers = [p for p in papers if p["category"].startswith(cat)]
    if args.tag:
        papers = [p for p in papers if args.tag in p.get("tags", [])]

    # 只需要下载状态为 to_download 的
    candidates = [p for p in papers if p.get("status") == "to_download"]

    print(f"=" * 60)
    print(f"待下载论文: {len(candidates)} 篇")
    if args.dry_run:
        print("模式: DRY-RUN (不会实际下载)")
    print(f"=" * 60)

    success = 0
    skipped = 0
    for paper in candidates:
        ok = download_paper(paper, dry_run=args.dry_run)
        if ok:
            success += 1
        else:
            skipped += 1

    print(f"\n完成: 成功 {success}, 跳过/失败 {skipped}")


if __name__ == "__main__":
    main()
