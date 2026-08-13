"""Real-loop claim/evidence/citation control for web-backed answers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from klara.core.loop import FinalAnswerDecision, LoopControllerEvent
from klara.core.messages import KlaraMessage
from klara.core.tools import ToolResult
from klara.services.evidence.contracts import (
    AnswerFrame,
    Citation,
    Claim,
    ClaimEvidenceLink,
    EvidenceJudgment,
    EvidencePack,
    EvidenceRecord,
    EvidenceStatus,
    VerificationDecision,
    VerifiedClaim,
)
from klara.services.evidence.controller import EvidenceController
from klara.services.web.research import WebResearchController


@dataclass
class EvidenceRuntimeController:
    """Require a verified structured answer before a web answer can leave the loop."""

    research: WebResearchController
    controller: EvidenceController = field(default_factory=EvidenceController)
    _frame: AnswerFrame | None = None
    _declared_abstention: bool = False
    _abstention_reason: str = ""
    _events: list[LoopControllerEvent] = field(default_factory=list)

    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        self._frame = None
        self._declared_abstention = False
        self._abstention_reason = ""
        self._events.clear()

    def system_prompt_suffix(self) -> str:
        if not self.research.state.active:
            return ""
        return "\n".join(
            [
                "<evidence_control>",
                "Before a web-backed final answer, call evidence_submit exactly once.",
                "List every material claim, its fetched source_id links, semantic judgment, and citation.",
                "Search candidates and snippets are never valid source_ids.",
                "Use abstain=true when required claims remain unsupported or contradicted.",
                "The runtime verifies fetched provenance, admissibility, links, citations, and duplicates.",
                "</evidence_control>",
            ]
        )

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        for result in results:
            if result.name != "evidence_submit" or not result.ok:
                continue
            try:
                payload = json.loads(result.content)
                self._frame = _parse_frame(payload)
                self._declared_abstention = bool(payload.get("abstain", False))
                self._abstention_reason = str(payload.get("abstention_reason", "")).strip()
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._frame = None
                self._queue(
                    "evidence.submission_rejected",
                    {"reason": "invalid_evidence_submission", "detail": str(exc)[:180]},
                )
                continue
            self._queue(
                "evidence.answer_submitted",
                {
                    "claim_count": len(self._frame.claims),
                    "link_count": len(self._frame.links),
                    "citation_count": len(self._frame.citations),
                    "declared_abstention": self._declared_abstention,
                },
            )

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        if not self.research.state.active:
            return FinalAnswerDecision(allowed=True, reason="evidence_off")
        if self._frame is None:
            return FinalAnswerDecision(
                allowed=False,
                reason="evidence_submission_required",
                feedback=(
                    "Call evidence_submit with the proposed final text and claim-level "
                    "links before answering. Use abstain=true if the evidence is insufficient."
                ),
            )
        if self._declared_abstention:
            replacement = self._frame.final_text.strip()
            if not replacement or not self._abstention_reason:
                return FinalAnswerDecision(
                    allowed=False,
                    reason="invalid_declared_abstention",
                    feedback="An abstention needs final_text and abstention_reason.",
                )
            abstained_claims = tuple(
                VerifiedClaim(
                    claim_id=claim.claim_id,
                    judgment=_declared_claim_judgment(claim.claim_id, self._frame),
                    source_ids=tuple(
                        sorted(
                            link.source_id
                            for link in self._frame.links
                            if link.claim_id == claim.claim_id
                        )
                    ),
                )
                for claim in self._frame.claims
            )
            decision = VerificationDecision(
                allowed=True,
                abstained=True,
                reason=self._abstention_reason,
                claims=abstained_claims,
            )
            pack = EvidencePack(())
        else:
            try:
                pack = self._pack()
                _validate_exact_witnesses(self._frame, pack)
                decision = self.controller.evaluate(self._frame, pack)
            except ValueError as exc:
                self._queue(
                    "evidence.verification_failed",
                    {"reason": "invalid_evidence_graph", "detail": str(exc)[:180]},
                )
                return FinalAnswerDecision(
                    allowed=False,
                    reason="invalid_evidence_graph",
                    feedback=f"Repair the evidence_submit graph: {str(exc)[:180]}",
                )
            replacement = self.controller.controlled_text(self._frame, decision)
        self._queue(
            "evidence.verification_completed",
            {
                "allowed": decision.allowed,
                "abstained": decision.abstained,
                "reason": decision.reason,
                "claims": [claim.to_dict() for claim in decision.claims],
                "selected_source_ids": list(decision.selected_source_ids),
                "citation_keys": list(decision.citation_keys),
            },
        )
        if not decision.allowed:
            return FinalAnswerDecision(
                allowed=False,
                reason="required_claims_not_supported",
                feedback=(
                    "Required claims did not pass evidence verification. Submit a corrected "
                    "answer or explicitly abstain. " + decision.reason
                ),
            )
        rendered = (
            replacement
            if decision.abstained
            else _render_citations(replacement, self._frame, pack)
        )
        return FinalAnswerDecision(
            allowed=True,
            reason="evidence_verified" if not decision.abstained else "evidence_abstained",
            replacement_content=rendered,
        )

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        return messages

    def drain_events(self) -> tuple[LoopControllerEvent, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events

    def _pack(self) -> EvidencePack:
        records = tuple(
            EvidenceRecord(
                source_id=source.source_id,
                title=source.title,
                url=source.final_url or source.url,
                content=source.content,
                fetched_at=source.fetched_at,
                content_hash=source.content_hash,
                status=EvidenceStatus(source.evidence_status),
                limitations=source.limitations,
            )
            for source in self.research.ledger.sources.values()
        )
        return EvidencePack(records)

    def _queue(self, event_type: str, payload: dict[str, object]) -> None:
        self._events.append(LoopControllerEvent(type=event_type, payload=payload))


def _parse_frame(payload: dict[str, Any]) -> AnswerFrame:
    claims = tuple(
        Claim(
            claim_id=_required(item, "claim_id"),
            text=_required(item, "text"),
            required=bool(item.get("required", True)),
        )
        for item in _objects(payload, "claims")
    )
    links = tuple(
        ClaimEvidenceLink(
            claim_id=_required(item, "claim_id"),
            source_id=_required(item, "source_id"),
            judgment=EvidenceJudgment(_required(item, "judgment")),
            support_note=str(item.get("support_note", "")),
        )
        for item in _objects(payload, "links")
    )
    citations = tuple(
        Citation(
            claim_id=_required(item, "claim_id"),
            source_id=_required(item, "source_id"),
        )
        for item in _objects(payload, "citations")
    )
    return AnswerFrame(
        claims=claims,
        links=links,
        citations=citations,
        final_text=_required(payload, "final_text"),
    )


def _objects(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be an array of objects")
    return value


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _render_citations(text: str, frame: AnswerFrame, pack: EvidencePack) -> str:
    if not frame.citations:
        return text
    sources = {record.source_id: record for record in pack.records}
    cited_ids = list(dict.fromkeys(citation.source_id for citation in frame.citations))
    lines = [text.rstrip(), "", "Sources:"]
    for index, source_id in enumerate(cited_ids, start=1):
        source = sources[source_id]
        label = source.title.strip() or source.url
        lines.append(f"{index}. [{label}]({source.url})")
    return "\n".join(lines)


def _validate_exact_witnesses(frame: AnswerFrame, pack: EvidencePack) -> None:
    sources = {record.source_id: record for record in pack.records}
    for link in frame.links:
        source = sources.get(link.source_id)
        if source is None:
            continue
        if link.judgment not in {
            EvidenceJudgment.SUPPORTED,
            EvidenceJudgment.CONTRADICTED,
        }:
            continue
        witness = " ".join(link.support_note.split())
        haystack = " ".join(source.content.split())
        if not witness or witness.casefold() not in haystack.casefold():
            raise ValueError(
                f"link {link.claim_id}::{link.source_id} lacks an exact fetched-text witness"
            )


def _declared_claim_judgment(claim_id: str, frame: AnswerFrame) -> EvidenceJudgment:
    judgments = {
        link.judgment for link in frame.links if link.claim_id == claim_id
    }
    if EvidenceJudgment.CONTRADICTED in judgments:
        return EvidenceJudgment.CONTRADICTED
    return EvidenceJudgment.INSUFFICIENT
