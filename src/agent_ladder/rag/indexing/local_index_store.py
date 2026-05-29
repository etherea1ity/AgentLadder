"""Local JSONL storage for Klara's index records."""

import json
from pathlib import Path

from agent_ladder.rag.indexing.index_record import IndexRecord


class LocalIndexStore:
    """Persist IndexRecords as transparent local JSONL."""

    def __init__(self, path: str | Path = "data/rag/index/index_records.jsonl") -> None:
        self.path = Path(path)

    def save_records(self, records: list[IndexRecord]) -> None:
        """Overwrite the JSONL store with the given records."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(record.model_dump_json() + "\n")

    def load_records(self) -> list[IndexRecord]:
        """Load IndexRecords from the JSONL store."""

        if not self.path.exists():
            return []

        records: list[IndexRecord] = []
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if not stripped:
                    continue
                records.append(IndexRecord.model_validate(json.loads(stripped)))
        return records
