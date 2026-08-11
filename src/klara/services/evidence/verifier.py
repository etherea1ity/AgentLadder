"""Deterministic enforcement for explicit claim/evidence judgments."""

from __future__ import annotations

from klara.services.evidence.contracts import (
    AnswerFrame,
    EvidenceJudgment,
    EvidencePack,
    EvidenceStatus,
    VerificationDecision,
    VerifiedClaim,
)


class EvidenceVerifier:
    """Validate joins and convert producer judgments into an allow/abstain result.

    This verifier is intentionally not a lexical similarity model. A producer
    or evaluator supplies the semantic claim/evidence judgment. The verifier
    enforces provenance, admissibility, citation, contradiction, and required
    claim policy without presenting string overlap as truth.
    """

    def verify(self, answer: AnswerFrame, evidence: EvidencePack) -> VerificationDecision:
        """Verify all references and block any unsupported required claim."""

        sources = {record.source_id: record for record in evidence.records}
        claims = {claim.claim_id: claim for claim in answer.claims}
        citation_keys = {citation.key for citation in answer.citations}
        link_keys = {f"{link.claim_id}::{link.source_id}" for link in answer.links}

        for link in answer.links:
            if link.claim_id not in claims:
                raise ValueError(f"link references unknown claim: {link.claim_id}")
            if link.source_id not in sources:
                raise ValueError(f"link references unknown source: {link.source_id}")
        for citation in answer.citations:
            if citation.claim_id not in claims:
                raise ValueError(
                    f"citation references unknown claim: {citation.claim_id}"
                )
            if citation.source_id not in sources:
                raise ValueError(
                    f"citation references unknown source: {citation.source_id}"
                )
            if citation.key not in link_keys:
                raise ValueError(
                    f"citation has no claim-evidence link: {citation.key}"
                )

        verified: list[VerifiedClaim] = []
        selected_source_ids: set[str] = set()
        for claim in answer.claims:
            links = [link for link in answer.links if link.claim_id == claim.claim_id]
            selected_source_ids.update(link.source_id for link in links)
            contradicted = tuple(
                sorted(
                    link.source_id
                    for link in links
                    if link.judgment == EvidenceJudgment.CONTRADICTED
                )
            )
            supported = tuple(
                sorted(
                    link.source_id
                    for link in links
                    if link.judgment == EvidenceJudgment.SUPPORTED
                    and sources[link.source_id].status == EvidenceStatus.ADMISSIBLE
                    and f"{claim.claim_id}::{link.source_id}" in citation_keys
                )
            )
            if contradicted:
                judgment = EvidenceJudgment.CONTRADICTED
                source_ids = contradicted
            elif supported:
                judgment = EvidenceJudgment.SUPPORTED
                source_ids = supported
            else:
                judgment = EvidenceJudgment.INSUFFICIENT
                source_ids = tuple(sorted(link.source_id for link in links))
            verified.append(
                VerifiedClaim(
                    claim_id=claim.claim_id,
                    judgment=judgment,
                    source_ids=source_ids,
                )
            )

        judgments = {item.claim_id: item.judgment for item in verified}
        blocking = [
            claim.claim_id
            for claim in answer.claims
            if claim.required and judgments[claim.claim_id] != EvidenceJudgment.SUPPORTED
        ]
        allowed = not blocking
        if allowed:
            reason = "all required claims are supported by admissible cited evidence"
        else:
            reason = "required claims need abstention: " + ", ".join(blocking)
        return VerificationDecision(
            allowed=allowed,
            abstained=not allowed,
            reason=reason,
            claims=tuple(verified),
            selected_source_ids=tuple(sorted(selected_source_ids)),
            citation_keys=tuple(sorted(citation_keys)),
        )
