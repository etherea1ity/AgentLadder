"""Final-answer controller built on the claim-level evidence verifier."""

from __future__ import annotations

from dataclasses import dataclass, field

from klara.services.evidence.contracts import (
    AnswerFrame,
    EvidencePack,
    VerificationDecision,
)
from klara.services.evidence.verifier import EvidenceVerifier


@dataclass
class EvidenceController:
    """Apply evidence policy and produce an explicit abstention when blocked."""

    verifier: EvidenceVerifier = field(default_factory=EvidenceVerifier)
    abstention_text: str = (
        "I cannot support every required claim with the available evidence."
    )

    def evaluate(
        self,
        answer: AnswerFrame,
        evidence: EvidencePack,
    ) -> VerificationDecision:
        """Return the deterministic evidence decision for a proposed answer."""

        return self.verifier.verify(answer, evidence)

    def controlled_text(
        self,
        answer: AnswerFrame,
        decision: VerificationDecision,
    ) -> str:
        """Return answer text only when the evidence decision permits it."""

        return answer.final_text if decision.allowed else self.abstention_text

