"""Small tokenizer for Klara's BM25 teaching retriever."""

from __future__ import annotations

import re

_TOKEN_PATTERN = re.compile(r"[\w][\w.\-_/]*", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase text while preserving code-like tokens such as AnswerFrameV1 and v0.2-rag-agent."""

    return [match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text)]
