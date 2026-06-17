from __future__ import annotations

from pathlib import Path

from agent_ladder.rag.contracts.agentic import VisualElement
from agent_ladder.knowledge.paper.corpus import PaperCorpus


class VisualAssetStore:
    def __init__(self, root: str | Path = "data/papers/fixtures") -> None:
        self.root = Path(root)

    def resolve(self, visual: VisualElement) -> str | None:
        if not visual.image_path:
            return None
        path = Path(visual.image_path)
        if path.is_absolute():
            return path.as_posix()
        if str(visual.image_path).startswith("data/"):
            return path.as_posix()
        return str((self.root / visual.paper_id / visual.image_path).as_posix())

    def load_visuals(self, paper_id: str | None = None) -> list[VisualElement]:
        return PaperCorpus(self.root).visuals(paper_id)
