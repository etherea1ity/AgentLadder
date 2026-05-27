from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_ladder.core.contracts.answer import AnswerState
from agent_ladder.core.contracts.ask import AskState
from agent_ladder.core.contracts.run import RunLog
from agent_ladder.core.contracts.usage import TokenUsage
from agent_ladder.llm.base import Message


class JsonlTracer:
    """Append minimal-agent runs to a JSONL trace file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(
        self,
        ask: AskState,
        answer: AnswerState,
        run: RunLog,
        *,
        prompt_messages: list[Message] | None = None,
        usage: TokenUsage | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": "v0.1",
            "ask": _to_jsonable_dict(ask),
            "prompt": {"messages": prompt_messages or []},
            "answer": _to_jsonable_dict(answer),
            "run": _to_jsonable_dict(run),
            "usage": _to_jsonable_dict(usage or run.usage),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _to_jsonable_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
