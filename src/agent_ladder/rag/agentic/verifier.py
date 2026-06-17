from __future__ import annotations

import re

from agent_ladder.rag.contracts.agentic import AnswerFrameV2, EvidencePack, VerificationResult


class CitationVerifier:
    def verify(self, answer: AnswerFrameV2, pack: EvidencePack) -> tuple[bool, list[str]]:
        source_ids = {item.source_id for item in pack.items}
        missing = [citation.source_id for citation in answer.citations if citation.source_id not in source_ids]
        return not missing, missing


class EvidenceVerifier:
    def verify(self, answer: AnswerFrameV2, pack: EvidencePack) -> tuple[bool, list[str]]:
        unsupported = []
        evidence_text = " ".join(
            [item.text for item in pack.items]
            + [item.visual.caption for item in pack.items if item.visual]
            + [item.visual.visual_summary or "" for item in pack.items if item.visual]
        ).lower()
        for claim in answer.claims:
            tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z\-]+", claim.lower()) if len(token) > 4]
            if tokens and not any(token in evidence_text for token in tokens[:4]):
                unsupported.append(claim)
        return not unsupported, unsupported


class VisualVerifier:
    def verify(self, answer: AnswerFrameV2) -> bool:
        return all(visual.image_path or visual.caption for visual in answer.visual_sources)


class LanguageVerifier:
    def verify(self, answer: AnswerFrameV2, output_language: str) -> bool:
        has_zh = bool(re.search(r"[\u4e00-\u9fff]", answer.final_text))
        if output_language == "zh":
            return has_zh
        if output_language == "en":
            return not has_zh
        return True


class DomainVerifier:
    def verify(self, pack: EvidencePack, allowed_domains: set[str] | None = None) -> bool:
        allowed_domains = allowed_domains or {"paper_corpus", "paper_visuals", "project_docs", "chapter_docs"}
        return all(item.source_domain in allowed_domains for item in pack.items)


class AnswerVerifier:
    def verify(self, answer: AnswerFrameV2, pack: EvidencePack, output_language: str) -> VerificationResult:
        citation_ok, missing = CitationVerifier().verify(answer, pack)
        evidence_ok, unsupported = EvidenceVerifier().verify(answer, pack)
        visual_ok = VisualVerifier().verify(answer)
        language_ok = LanguageVerifier().verify(answer, output_language)
        domain_ok = DomainVerifier().verify(pack)
        if citation_ok and evidence_ok and visual_ok and language_ok and domain_ok:
            return VerificationResult(status="passed", reason="all checks passed")
        status = "insufficient" if pack.evidence_status == "insufficient" else "failed"
        return VerificationResult(status=status, citation_ok=citation_ok, evidence_ok=evidence_ok and domain_ok, visual_ok=visual_ok, language_ok=language_ok, missing_source_ids=missing, unsupported_claims=unsupported, reason="verification failed")
