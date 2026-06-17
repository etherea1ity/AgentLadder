"""
Phase B: Open-access Validation
检查每篇候选论文是否有合法 open-access PDF。

合法来源: arXiv, OpenReview, ACL Anthology, official project page,
          official university/lab page, publisher open-access page

禁止: paywall bypass, sci-hub, 非授权镜像, 来历不明 PDF

用法:
    python scripts/ingest/validate_access.py
    python scripts/ingest/validate_access.py --limit 5
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAPERS_DIR = PROJECT_ROOT / "data" / "papers"
MANIFEST_CANDIDATES = PAPERS_DIR / "manifest_candidates.jsonl"
ACCESS_REPORT = PAPERS_DIR / "quality_reports" / "access_report.md"

# arXiv 是明确允许的 open-access 来源
OPEN_ACCESS_SOURCES = [
    "arxiv.org",
    "openreview.net",
    "aclanthology.org",
    "proceedings.mlr.press",  # PMLR
    "papers.nips.cc",
    "openaccess.thecvf.com",  # CVPR/ICCV open access
]


def check_url(url: str, timeout: int = 10) -> dict:
    """检查 URL 是否可访问，返回状态信息。"""
    result = {"reachable": False, "status_code": None, "note": ""}
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "AgentLadder-PaperBot/1.0 (academic research)")
        resp = urllib.request.urlopen(req, timeout=timeout)
        result["reachable"] = True
        result["status_code"] = resp.getcode()
    except urllib.error.HTTPError as e:
        result["reachable"] = False
        result["status_code"] = e.code
        result["note"] = f"HTTP {e.code}"
    except Exception as e:
        result["reachable"] = False
        result["note"] = str(e)[:100]
    return result


def classify_source(url: str) -> tuple[str, str]:
    """分类来源类型。返回 (source_type, note)。"""
    url_lower = url.lower()

    if "arxiv.org" in url_lower:
        if "/pdf/" in url_lower or url_lower.endswith(".pdf"):
            return "open_access", "arxiv PDF"
        return "open_access", "arxiv abstract (PDF available)"

    if "openreview.net" in url_lower:
        return "open_access", "OpenReview"

    if "aclanthology.org" in url_lower:
        return "open_access", "ACL Anthology"

    if any(s in url_lower for s in ["mlr.press", "proceedings.mlr"]):
        return "open_access", "PMLR"

    if "papers.nips.cc" in url_lower:
        return "open_access", "NeurIPS proceedings"

    if "openaccess.thecvf.com" in url_lower:
        return "open_access", "CVF open access"

    if any(s in url_lower for s in ["doi.org", "acm.org", "springer.com", "elsevier.com", "ieee.org"]):
        return "uncertain", "publisher — may require subscription"

    if "github.com" in url_lower:
        return "metadata_only", "GitHub repo (no PDF)"

    return "uncertain", "unknown source type"


def validate_paper(paper: dict) -> dict:
    """验证单篇论文的访问状态。"""
    paper_id = paper["paper_id"]
    pdf_url = paper.get("possible_pdf_url", "")
    arxiv_id = paper.get("arxiv_id", "")

    # 如果有 arxiv ID，确认是 open_access
    if arxiv_id:
        arxiv_pdf = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        result = check_url(arxiv_pdf)
        if result["reachable"]:
            return {
                "access_status": "open_access",
                "access_note": f"arXiv (verified, {result['status_code']})",
                "verified_pdf_url": arxiv_pdf,
            }

    # 检查 possible_pdf_url
    if pdf_url:
        source_type, note = classify_source(pdf_url)
        if source_type == "open_access":
            result = check_url(pdf_url)
            if result["reachable"]:
                return {
                    "access_status": "open_access",
                    "access_note": f"{note} (verified, {result['status_code']})",
                    "verified_pdf_url": pdf_url,
                }
            else:
                return {
                    "access_status": "uncertain",
                    "access_note": f"{note} (unreachable: {result['note']})",
                    "verified_pdf_url": None,
                }
        else:
            return {
                "access_status": source_type,
                "access_note": note,
                "verified_pdf_url": pdf_url if source_type == "open_access" else None,
            }

    return {
        "access_status": "uncertain",
        "access_note": "no PDF URL available",
        "verified_pdf_url": None,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase B: Open-access validation")
    parser.add_argument("--limit", type=int, default=0, help="Limit papers to check")
    args = parser.parse_args()

    # 加载候选清单
    candidates = []
    with open(MANIFEST_CANDIDATES, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

    if args.limit:
        candidates = candidates[: args.limit]

    print(f"Phase B: Validating access for {len(candidates)} candidates...")

    results = {"open_access": 0, "uncertain": 0, "metadata_only": 0, "failed": []}

    for paper in candidates:
        paper_id = paper["paper_id"]
        validation = validate_paper(paper)

        paper["access_status"] = validation["access_status"]
        paper["access_note"] = validation.get("access_note", "")
        paper["verified_pdf_url"] = validation.get("verified_pdf_url")
        paper.pop("possible_pdf_url", None)

        results[validation["access_status"]] += 1

        symbol = "OK" if validation["access_status"] == "open_access" else "??"
        print(f"  [{symbol}] {paper_id}: {validation['access_status']} - {validation.get('access_note', '')[:60]}")

        if validation["access_status"] != "open_access":
            results["failed"].append(paper_id)

    print(f"\nResults: {results['open_access']} open_access, "
          f"{results['uncertain']} uncertain, "
          f"{results['metadata_only']} metadata_only")

    # 生成 access report
    report_lines = [
        "# Open-access Validation Report",
        f"\nGenerated: 2026-05-31\n",
        f"## Summary\n",
        f"| Status | Count |",
        f"|--------|-------|",
        f"| open_access | {results['open_access']} |",
        f"| uncertain | {results['uncertain']} |",
        f"| metadata_only | {results['metadata_only']} |",
    ]

    if results["failed"]:
        report_lines.append(f"\n## Non-open-access Papers\n")
        for pid in results["failed"]:
            for p in candidates:
                if p["paper_id"] == pid:
                    report_lines.append(f"- **{pid}**: {p['title'][:80]} — {p.get('access_note', '')}")
                    break

    report_lines.append(f"\n## All Candidates\n")
    for p in candidates:
        report_lines.append(
            f"- **{p['paper_id']}**: `{p['access_status']}` — {p['title'][:80]} "
            f"({p.get('access_note', '')})"
        )

    ACCESS_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCESS_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(f"\nAccess report saved to: {ACCESS_REPORT}")


if __name__ == "__main__":
    main()
