"""
使用 MinerU 将下载的 PDF 转换为 Markdown。

前置条件:
    pip install magic-pdf
    # 或使用 OpenXLab MinerU 在线服务

用法:
    python scripts/papers/convert_pdfs.py                          # 转换全部 PDF
    python scripts/papers/convert_pdfs.py --category 01            # 只转换某个分类
    python scripts/papers/convert_pdfs.py --id paper-0101          # 转换指定论文
    python scripts/papers/convert_pdfs.py --dry-run                # 预览

MinerU 在线 API 方式 (推荐，处理图片/表格效果更好):
    设置环境变量:
        MINERU_API_TOKEN=你的OpenXLab_token
        MINERU_ENDPOINT=https://mineru.openxlab.org.cn/api/v1

或本地方式:
    magic-pdf -p input.pdf -o output_dir
"""

import argparse
import os
import subprocess
import sys
import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAPERS_DIR = PROJECT_ROOT / "data" / "raw" / "papers"
INDEX_FILE = PAPERS_DIR / "paper-index.yaml"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "papers"


def load_index() -> dict:
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def convert_local(pdf_path: Path, output_dir: Path) -> bool:
    """使用本地 MinerU (magic-pdf) 转换"""
    try:
        subprocess.run(
            ["magic-pdf", "-p", str(pdf_path), "-o", str(output_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def convert_api(pdf_path: Path, output_dir: Path) -> bool:
    """使用 MinerU 在线 API 转换 (OpenXLab)"""
    token = os.environ.get("MINERU_API_TOKEN", "")
    endpoint = os.environ.get("MINERU_ENDPOINT", "https://mineru.openxlab.org.cn/api/v1")

    if not token:
        print("    请设置 MINERU_API_TOKEN 环境变量")
        return False

    # MinerU API 调用: 上传 PDF, 轮询结果, 下载 Markdown
    # 这是示例框架，具体请参考 MinerU 最新 API 文档
    print(f"    [TODO] MinerU API 转换: {pdf_path.name}")
    print(f"    API endpoint: {endpoint}")
    return False


def convert_paper(paper: dict, mode: str = "local", dry_run: bool = False) -> bool:
    """转换单篇论文的 PDF 为 Markdown。"""
    paper_id = paper["id"]
    category = paper["category"]

    pdf_path = PAPERS_DIR / category / f"{paper_id}.pdf"
    if not pdf_path.exists():
        print(f"  [SKIP] {paper_id}: PDF 不存在")
        return False

    md_output_dir = PROCESSED_DIR / category / paper_id
    md_output_dir.mkdir(parents=True, exist_ok=True)

    md_path = md_output_dir / f"{paper_id}.md"
    if md_path.exists():
        print(f"  [EXISTS] {paper_id}: {md_path}")
        return True

    if dry_run:
        print(f"  [DRY-RUN] {paper_id}: {pdf_path} -> {md_output_dir}")
        return True

    print(f"  [CONVERT] {paper_id}: {paper['title'][:60]}...")

    if mode == "api":
        ok = convert_api(pdf_path, md_output_dir)
    else:
        ok = convert_local(pdf_path, md_output_dir)

    if ok:
        paper["status"] = "converted"
        print(f"    -> {md_path}")
    else:
        print(f"  [FAIL] {paper_id}: 转换失败")

    return ok


def main():
    parser = argparse.ArgumentParser(description="使用 MinerU 将论文 PDF 转为 Markdown")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--category", type=str, help="限定分类")
    parser.add_argument("--id", type=str, help="指定论文 ID")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["local", "api"],
        default="local",
        help="转换模式: local (magic-pdf) 或 api (OpenXLab MinerU)",
    )
    args = parser.parse_args()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    index = load_index()
    papers = index["papers"]

    if args.id:
        papers = [p for p in papers if p["id"] == args.id]
    if args.category:
        cat = f"0{args.category}-" if len(args.category) == 1 else f"{args.category}-"
        papers = [p for p in papers if p["category"].startswith(cat)]

    # 下载的或已有的都尝试转换
    candidates = [p for p in papers if p.get("status") in ("to_download", "downloaded")]

    # 也包含已有 PDF 但未转换的
    for p in papers:
        if p.get("status") not in ("to_download", "downloaded", "converted", "indexed"):
            pdf_path = PAPERS_DIR / p["category"] / f"{p['id']}.pdf"
            if pdf_path.exists():
                p["status"] = "downloaded"
                candidates.append(p)

    print(f"=" * 60)
    print(f"待转换论文: {len(candidates)} 篇")
    print(f"模式: {args.mode}")
    if args.dry_run:
        print("DRY-RUN: 不会实际转换")
    print(f"=" * 60)

    success = 0
    for paper in candidates:
        if convert_paper(paper, mode=args.mode, dry_run=args.dry_run):
            success += 1

    print(f"\n完成: 成功 {success}, 跳过/失败 {len(candidates) - success}")


if __name__ == "__main__":
    main()
