from __future__ import annotations

from agent_ladder.rag.contracts.agentic import FetchResult, VisualElement
from agent_ladder.rag.contracts.source import SourceCard


class PaperSourceCardBuilder:
    def from_fetch(self, result: FetchResult) -> SourceCard:
        return SourceCard(
            source_id=result.source_id,
            title=result.title,
            source_path=result.metadata.get("source_path", result.fetch_id),
            source_type=result.source_type,
            paper_id=result.paper_id,
            page=result.page,
            asset_path=result.image_path,
            source_domain=result.source_domain,
            evidence_role=result.evidence_role,
            used_chunk_ids=[result.fetch_id] if result.source_type == "paper_chunk" else [],
            summary=result.text[:220] if result.text else result.metadata.get("caption"),
            metadata=result.metadata,
        )

    def from_visual(self, visual: VisualElement, *, title: str) -> SourceCard:
        source_type = "paper_table" if visual.visual_type == "table" else "paper_figure"
        return SourceCard(
            source_id=visual.visual_id,
            title=f"{title}: {visual.label}",
            source_path=visual.image_path or visual.visual_id,
            source_type=source_type,
            paper_id=visual.paper_id,
            page=visual.page,
            asset_path=visual.image_path,
            source_domain=visual.source_domain,
            evidence_role=visual.evidence_role,
            summary=visual.caption,
            metadata={"visual_summary": visual.visual_summary},
        )
