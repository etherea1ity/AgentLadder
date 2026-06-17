from __future__ import annotations

from agent_ladder.rag.contracts.agentic import AnswerFrameV2, EvidencePack, RequestSpec
from agent_ladder.rag.contracts.source import Citation


class AnswerWriter:
    """Writer constrained to EvidencePack; raw chunks are not accepted."""

    def write(self, request: RequestSpec, pack: EvidencePack) -> AnswerFrameV2:
        if pack.evidence_status == "insufficient":
            return AnswerFrameV2(question=request.original_query, mode="insufficient_info", final_text=_insufficient_text(request), evidence_items=[], sources=[], citations=[])
        visible_items = pack.items[: request.requirements.requested_count or len(pack.items)]
        visible_source_ids = {item.source_id for item in visible_items}
        visible_sources = [card for card in pack.source_cards if card.source_id in visible_source_ids]
        claims = [_claim_from_item(item) for item in visible_items]
        citations = [Citation(citation_id=f"cit_{idx}", source_id=item.source_id, chunk_id=item.source_id, label=f"Source {idx}", quote_or_summary=item.text[:220] or (item.visual.caption if item.visual else "")) for idx, item in enumerate(visible_items, start=1)]
        visual_sources = [item.visual for item in visible_items if item.visual is not None]
        rendered_assets = [{"source_id": visual.visual_id, "image_path": visual.image_path, "caption": visual.caption, "page": visual.page} for visual in visual_sources]
        text = render_answer(request, pack, claims)
        return AnswerFrameV2(question=request.original_query, mode="rag", claims=claims, sources=visible_sources, evidence_items=visible_items, citations=citations, visual_sources=visual_sources, rendered_assets=rendered_assets, final_text=text)


def render_answer(request: RequestSpec, pack: EvidencePack, claims: list[str]) -> str:
    zh = request.language_plan.output_language == "zh"
    count = request.requirements.requested_count
    if request.output_style.answer_style == "explanatory" and not count:
        return render_explanatory_answer(request, pack)
    if zh:
        header = "我是 Klara。基于本地知识库与论文库的受控证据搜索，我会把证据先整理成可核查的路线，而不是自由发挥："
        lines = [header]
        for idx, item in enumerate(pack.items[: count or len(pack.items)], start=1):
            kind = "视觉证据" if item.visual is not None or item.evidence_type in {"figure", "table", "equation", "page_image", "visual"} else "文本证据"
            metadata = item.metadata or {}
            year = metadata.get("year")
            venue = metadata.get("venue")
            tags = ", ".join(str(tag) for tag in metadata.get("method_tags", [])[:4]) if isinstance(metadata.get("method_tags"), list) else ""
            meta = "；".join(str(part) for part in [year, venue, tags] if part)
            lines.append(f"{idx}. {item.title}{f'（{meta}）' if meta else ''}：{item.text[:120]}（{kind}）")
        if pack.evidence_status == "weak" and count:
            lines.append(f"注意：这是 partial result；本地证据不足以可靠填满 {count} 个强相关结果。")
        return "\n".join(lines)
    lines = ["I’m Klara. Based on the unified local controlled evidence search, I will organize the evidence into auditable routes rather than free-form speculation:"]
    for idx, item in enumerate(pack.items[: count or len(pack.items)], start=1):
        kind = "visual evidence" if item.visual is not None or item.evidence_type in {"figure", "table", "equation", "page_image", "visual"} else "text evidence"
        metadata = item.metadata or {}
        year = metadata.get("year")
        venue = metadata.get("venue")
        tags = ", ".join(str(tag) for tag in metadata.get("method_tags", [])[:4]) if isinstance(metadata.get("method_tags"), list) else ""
        meta = "; ".join(str(part) for part in [year, venue, tags] if part)
        lines.append(f"{idx}. {item.title}{f' ({meta})' if meta else ''}: {item.text[:140]} ({kind})")
    if pack.evidence_status == "weak" and count:
        lines.append(f"Note: this is a partial result; the local corpus does not provide {count} strong matching sources.")
    return "\n".join(lines)


def render_explanatory_answer(request: RequestSpec, pack: EvidencePack) -> str:
    zh = request.language_plan.output_language == "zh"
    items = pack.items[: min(4, len(pack.items))]
    if zh:
        lines = ["我是 Klara。基于本地知识库与论文库的受控证据搜索，我会先给出可核查的解释，而不是把检索片段直接堆给你。"]
        if items:
            lead = items[0]
            lines.append(f"核心证据：{_paper_line(lead, zh=True)}。")
            lines.append(f"简要理解：{_clean_evidence_text(lead.text, 220)}")
            if len(items) > 1:
                lines.append("相关证据：")
                for item in items[1:]:
                    lines.append(f"- {_paper_line(item, zh=True)}：{_clean_evidence_text(item.text, 120)}")
        if pack.evidence_status == "weak":
            lines.append("注意：本地证据偏弱，我会把这个回答限定在已检索到的论文证据内。")
        return "\n".join(lines)
    lines = ["I’m Klara. Based on the unified local controlled evidence search, I’ll explain this from auditable local evidence rather than free-form speculation."]
    if items:
        lead = items[0]
        lines.append(f"Core evidence: {_paper_line(lead, zh=False)}.")
        lines.append(f"Short explanation: {_clean_evidence_text(lead.text, 260)}")
        if len(items) > 1:
            lines.append("Related evidence:")
            for item in items[1:]:
                lines.append(f"- {_paper_line(item, zh=False)}: {_clean_evidence_text(item.text, 140)}")
    if pack.evidence_status == "weak":
        lines.append("Note: the local evidence is weak, so I’m keeping the answer bounded to retrieved local evidence.")
    return "\n".join(lines)


def _paper_line(item, *, zh: bool) -> str:
    metadata = item.metadata or {}
    year = metadata.get("year")
    venue = metadata.get("venue")
    tags = ", ".join(str(tag) for tag in metadata.get("method_tags", [])[:4]) if isinstance(metadata.get("method_tags"), list) else ""
    sep = "；" if zh else "; "
    meta = sep.join(str(part) for part in [year, venue, tags] if part)
    return f"{item.title}{f'（{meta}）' if zh and meta else f' ({meta})' if meta else ''}"


def _clean_evidence_text(text: str, limit: int) -> str:
    lines = []
    skip_prefixes = ("#", "YEAR:", "VENUE:", "URL:", "PDF_URL:", "ARXIV_ID:", "DOMAIN:", "METHOD_TAGS:", "BENCHMARKS:")
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(skip_prefixes):
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        lines.append(line)
    cleaned = " ".join(lines)
    for marker in ["One Sentence Summary", "Why It Matters", "Core Idea"]:
        cleaned = cleaned.replace(marker, "")
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]


def _claim_from_item(item) -> str:
    if item.visual:
        return f"{item.title} provides visual evidence: {item.visual.caption}"
    return f"{item.title} supports: {item.text[:120]}"


def _insufficient_text(request: RequestSpec) -> str:
    return "我是 Klara。当前本地证据不足，我不能可靠回答或编造本地知识信息。" if request.language_plan.output_language == "zh" else "I’m Klara. The local evidence is insufficient, so I cannot answer reliably or fabricate local knowledge details."
