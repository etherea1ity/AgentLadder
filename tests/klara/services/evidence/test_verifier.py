from __future__ import annotations

import pytest

from klara.services.evidence import (
    AnswerFrame,
    Citation,
    Claim,
    ClaimEvidenceLink,
    EvidenceController,
    EvidenceJudgment,
    EvidencePack,
    EvidenceRecord,
    EvidenceStatus,
)


def _record(status: EvidenceStatus = EvidenceStatus.ADMISSIBLE) -> EvidenceRecord:
    return EvidenceRecord(
        source_id="src-1",
        title="Source",
        url="https://example.test/source",
        content="The supported fact is present.",
        fetched_at="2026-08-11T00:00:00+00:00",
        status=status,
    )


def _answer(
    judgment: EvidenceJudgment,
    *,
    cited: bool = True,
    source_id: str = "src-1",
) -> AnswerFrame:
    return AnswerFrame(
        claims=(Claim(claim_id="claim-1", text="The fact is true."),),
        links=(
            ClaimEvidenceLink(
                claim_id="claim-1",
                source_id=source_id,
                judgment=judgment,
            ),
        ),
        citations=(
            (Citation(claim_id="claim-1", source_id=source_id),)
            if cited
            else ()
        ),
        final_text="The fact is true.",
    )


def test_supported_cited_required_claim_is_allowed() -> None:
    controller = EvidenceController()

    decision = controller.evaluate(
        _answer(EvidenceJudgment.SUPPORTED),
        EvidencePack((_record(),)),
    )

    assert decision.allowed is True
    assert decision.abstained is False
    assert decision.claims[0].judgment == EvidenceJudgment.SUPPORTED
    assert controller.controlled_text(_answer(EvidenceJudgment.SUPPORTED), decision) == (
        "The fact is true."
    )


@pytest.mark.parametrize(
    ("answer", "record", "expected"),
    [
        (
            _answer(EvidenceJudgment.SUPPORTED, cited=False),
            _record(),
            EvidenceJudgment.INSUFFICIENT,
        ),
        (
            _answer(EvidenceJudgment.CONTRADICTED),
            _record(),
            EvidenceJudgment.CONTRADICTED,
        ),
        (
            _answer(EvidenceJudgment.INSUFFICIENT, cited=False),
            _record(),
            EvidenceJudgment.INSUFFICIENT,
        ),
        (
            _answer(EvidenceJudgment.SUPPORTED, cited=False),
            _record(EvidenceStatus.STALE),
            EvidenceJudgment.INSUFFICIENT,
        ),
        (
            _answer(EvidenceJudgment.SUPPORTED, cited=False),
            _record(EvidenceStatus.IRRELEVANT),
            EvidenceJudgment.INSUFFICIENT,
        ),
    ],
)
def test_unsupported_required_claims_force_explicit_abstention(
    answer: AnswerFrame,
    record: EvidenceRecord,
    expected: EvidenceJudgment,
) -> None:
    controller = EvidenceController()

    decision = controller.evaluate(answer, EvidencePack((record,)))

    assert decision.allowed is False
    assert decision.abstained is True
    assert decision.claims[0].judgment == expected
    assert controller.controlled_text(answer, decision) == controller.abstention_text


def test_dangling_source_link_is_rejected() -> None:
    controller = EvidenceController()

    with pytest.raises(ValueError, match="unknown source"):
        controller.evaluate(
            _answer(EvidenceJudgment.SUPPORTED, source_id="missing"),
            EvidencePack((_record(),)),
        )


def test_citation_without_explicit_link_is_rejected() -> None:
    answer = AnswerFrame(
        claims=(Claim(claim_id="claim-1", text="The fact is true."),),
        links=(),
        citations=(Citation(claim_id="claim-1", source_id="src-1"),),
        final_text="The fact is true.",
    )

    with pytest.raises(ValueError, match="no claim-evidence link"):
        EvidenceController().evaluate(answer, EvidencePack((_record(),)))
