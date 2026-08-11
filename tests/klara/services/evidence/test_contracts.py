from __future__ import annotations

from dataclasses import fields

import pytest

from klara.services.evidence import (
    AnswerFrame,
    Citation,
    Claim,
    ClaimEvidenceLink,
    EvidenceJudgment,
    EvidencePack,
    EvidenceRecord,
)


def test_evidence_record_binds_content_hash() -> None:
    record = EvidenceRecord(
        source_id="src-1",
        title="Source",
        url="https://example.test/source",
        content="stable evidence\n",
        fetched_at="2026-08-11T00:00:00+00:00",
    )

    assert len(record.content_hash) == 64
    assert record.to_dict()["content_hash"] == record.content_hash


def test_evidence_record_rejects_wrong_hash() -> None:
    with pytest.raises(ValueError, match="content hash mismatch"):
        EvidenceRecord(
            source_id="src-1",
            title="Source",
            url="https://example.test/source",
            content="stable evidence",
            fetched_at="2026-08-11T00:00:00+00:00",
            content_hash="0" * 64,
        )


def test_evidence_pack_is_writer_boundary_without_raw_chunks() -> None:
    field_names = {item.name for item in fields(EvidencePack)}

    assert field_names == {"records"}
    assert "raw_chunks" not in field_names
    assert "retrieval_chunks" not in field_names


def test_answer_frame_rejects_duplicate_citation() -> None:
    citation = Citation(claim_id="claim-1", source_id="src-1")

    with pytest.raises(ValueError, match="duplicate citation"):
        AnswerFrame(
            claims=(Claim(claim_id="claim-1", text="A claim"),),
            links=(
                ClaimEvidenceLink(
                    claim_id="claim-1",
                    source_id="src-1",
                    judgment=EvidenceJudgment.SUPPORTED,
                ),
            ),
            citations=(citation, citation),
            final_text="A claim",
        )

