"""Load local markdown files together with sidecar metadata."""

from pathlib import Path
from typing import Any

import yaml

from agent_ladder.rag.contracts.document import Document, DocumentMetadata


class LocalMarkdownLoader:
    """Read `.md` files and their sibling `.metadata.yaml` files as Documents."""

    def __init__(self, root: str | Path = "data/knowledge") -> None:
        self.root = Path(root)

    def load_directory(self, root: str | Path | None = None) -> list[Document]:
        """Load every markdown document under a directory."""

        directory = Path(root) if root is not None else self.root
        return [self.load_file(path) for path in sorted(directory.rglob("*.md"))]

    def load_file(self, markdown_path: str | Path) -> Document:
        """Load a markdown document and its required sidecar metadata."""

        path = Path(markdown_path)
        metadata_path = path.with_suffix(".metadata.yaml")
        if not metadata_path.exists():
            raise FileNotFoundError(f"Missing metadata file for {path}: {metadata_path}")

        text = path.read_text(encoding="utf-8").strip()
        raw_metadata = self._read_metadata(metadata_path)

        document_id = str(raw_metadata.pop("document_id"))
        title = str(raw_metadata.get("title") or self._first_heading(text) or path.stem)
        raw_metadata.setdefault("title", title)
        raw_metadata.setdefault("source_path", path.as_posix())
        raw_metadata.setdefault("source_type", "markdown")

        return Document(
            document_id=document_id,
            title=title,
            text=text,
            metadata=DocumentMetadata.model_validate(raw_metadata),
        )

    def _read_metadata(self, metadata_path: Path) -> dict[str, Any]:
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Metadata must be a mapping: {metadata_path}")
        if "document_id" not in data:
            raise ValueError(f"Metadata must include document_id: {metadata_path}")
        return data

    def _first_heading(self, text: str) -> str | None:
        for line in text.splitlines():
            if line.startswith("# "):
                return line.removeprefix("# ").strip()
        return None
