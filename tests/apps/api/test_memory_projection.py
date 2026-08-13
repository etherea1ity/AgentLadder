from __future__ import annotations

import json

from apps.api.services.run_event_projector import RunEventProjector
from klara.core.events import KlaraEvent


def test_memory_events_project_without_private_content() -> None:
    event = KlaraEvent(
        type="memory.retrieved",
        run_id="run-memory",
        seq=1,
        timestamp="2026-08-13T00:00:00+00:00",
        payload={
            "memory_id": "mem-1",
            "result_count": 1,
            "content": "private preference phrase",
            "query": "private query",
            "provenance": {"note": "private note"},
        },
    )

    projected = RunEventProjector().project(event)[0]
    rendered = json.dumps(projected.payload)
    assert projected.event_type == "memory.retrieved"
    assert projected.payload["content_exposed"] is False
    assert "private preference phrase" not in rendered
    assert "private query" not in rendered
    assert "private note" not in rendered
