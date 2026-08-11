"""Stable contracts for claim-level evidence control.

The runtime's web ledger answers whether enough sources were fetched. These
contracts answer a different question: whether every required answer claim is
supported by an admissible source and an explicit citation. They deliberately
carry evidence records, never retrieval chunks or provider-hidden reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
from typing import Any


class EvidenceJudgment(StrEnum):
    """Producer-visible relation between one claim and one evidence record."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class EvidenceStatus(StrEnum):
    """Whether an evidence record may support a final answer."""

    ADMISSIBLE = "admissible"
    STALE = "stale"
    IRRELEVANT = "irrelevant"


def content_sha256(content: str) -> str:
    """Return the stable hash used to identify normalized evidence content."""

    normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    """One bounded, provenance-bearing record visible to an answer writer."""

    source_id: str
    title: str
    url: str
    content: str
    fetched_at: str
    content_hash: str = ""
    status: EvidenceStatus = EvidenceStatus.ADMISSIBLE
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate identity and bind the record to its exact content."""

        _require_id(self.source_id, "source_id")
        if not self.content.strip():
            raise ValueError("evidence content must not be empty")
        expected_hash = content_sha256(self.content)
        if self.content_hash and self.content_hash != expected_hash:
            raise ValueError(f"content hash mismatch for source {self.source_id}")
        object.__setattr__(self, "content_hash", expected_hash)
        object.__setattr__(self, "status", EvidenceStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record without introducing raw retrieval chunks."""

        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "fetched_at": self.fetched_at,
            "content_hash": self.content_hash,
            "status": self.status.value,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class Claim:
    """One stable answer claim that can be verified independently."""

    claim_id: str
    text: str
    required: bool = True

    def __post_init__(self) -> None:
        """Reject claims that cannot be linked or evaluated."""

        _require_id(self.claim_id, "claim_id")
        if not self.text.strip():
            raise ValueError("claim text must not be empty")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible claim."""

        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "required": self.required,
        }


@dataclass(frozen=True)
class ClaimEvidenceLink:
    """Explicit, auditable evidence judgment for a claim/source pair."""

    claim_id: str
    source_id: str
    judgment: EvidenceJudgment
    support_note: str = ""

    def __post_init__(self) -> None:
        """Normalize the finite judgment vocabulary."""

        _require_id(self.claim_id, "claim_id")
        _require_id(self.source_id, "source_id")
        object.__setattr__(self, "judgment", EvidenceJudgment(self.judgment))

    def to_dict(self) -> dict[str, Any]:
        """Return the public link contract."""

        return {
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "judgment": self.judgment.value,
            "support_note": self.support_note,
        }


@dataclass(frozen=True)
class Citation:
    """A final-answer citation joining one claim to one evidence record."""

    claim_id: str
    source_id: str

    def __post_init__(self) -> None:
        """Require stable join keys."""

        _require_id(self.claim_id, "claim_id")
        _require_id(self.source_id, "source_id")

    @property
    def key(self) -> str:
        """Return the canonical scorer key."""

        return f"{self.claim_id}::{self.source_id}"

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible citation."""

        return {"claim_id": self.claim_id, "source_id": self.source_id}


@dataclass(frozen=True)
class EvidencePack:
    """The only evidence collection exposed to an answer writer."""

    records: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        """Reject duplicate source identities."""

        _require_unique((record.source_id for record in self.records), "source_id")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bounded evidence pack."""

        return {"records": [record.to_dict() for record in self.records]}


@dataclass(frozen=True)
class AnswerFrame:
    """Structured proposed answer consumed by the evidence verifier."""

    claims: tuple[Claim, ...]
    links: tuple[ClaimEvidenceLink, ...]
    citations: tuple[Citation, ...]
    final_text: str

    def __post_init__(self) -> None:
        """Reject duplicate claim identities and citation keys."""

        _require_unique((claim.claim_id for claim in self.claims), "claim_id")
        _require_unique((citation.key for citation in self.citations), "citation")
        _require_unique(
            (f"{link.claim_id}::{link.source_id}" for link in self.links),
            "claim-evidence link",
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the proposed answer for fixtures and reports."""

        return {
            "claims": [claim.to_dict() for claim in self.claims],
            "links": [link.to_dict() for link in self.links],
            "citations": [citation.to_dict() for citation in self.citations],
            "final_text": self.final_text,
        }


@dataclass(frozen=True)
class VerifiedClaim:
    """Deterministic final judgment for one claim."""

    claim_id: str
    judgment: EvidenceJudgment
    source_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize one claim decision."""

        return {
            "claim_id": self.claim_id,
            "judgment": self.judgment.value,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class VerificationDecision:
    """Final-answer control result produced from one answer and evidence pack."""

    allowed: bool
    abstained: bool
    reason: str
    claims: tuple[VerifiedClaim, ...]
    selected_source_ids: tuple[str, ...] = ()
    citation_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a trace- and report-safe decision payload."""

        return {
            "allowed": self.allowed,
            "abstained": self.abstained,
            "reason": self.reason,
            "claims": [claim.to_dict() for claim in self.claims],
            "selected_source_ids": list(self.selected_source_ids),
            "citation_keys": list(self.citation_keys),
        }


def _require_id(value: str, label: str) -> None:
    """Raise when a join key is empty or whitespace-only."""

    if not value.strip():
        raise ValueError(f"{label} must not be empty")


def _require_unique(values: Any, label: str) -> None:
    """Raise when an iterable contains a duplicate identity."""

    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {label}: {sorted(duplicates)}")

