from __future__ import annotations

import json

from apps.api.services.run_event_projector import RunEventProjector
from klara.core.events import KlaraEvent


def test_evidence_verification_projection_omits_private_answer_and_witness() -> None:
    event = KlaraEvent(
        type="evidence.verification_completed",
        run_id="run-evidence",
        seq=1,
        timestamp="2026-08-13T00:00:00+00:00",
        payload={
            "allowed": True,
            "abstained": False,
            "final_text": "private draft",
            "support_note": "private witness",
            "claims": [
                {"claim_id": "claim-1", "judgment": "supported", "source_ids": ["src-1"]}
            ],
            "selected_source_ids": ["src-1"],
            "citation_keys": ["claim-1::src-1"],
        },
    )

    projected = RunEventProjector().project(event)[0]
    rendered = json.dumps(projected.payload)

    assert projected.event_type == "evidence.verification_completed"
    assert "private draft" not in rendered
    assert "private witness" not in rendered
    assert projected.payload["private_evidence_content_exposed"] is False
