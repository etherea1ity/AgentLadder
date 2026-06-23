"""Generic web research state, evidence ledger, and loop controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import re
from typing import Literal
from urllib.parse import urlparse, urlunparse

from klara.core.loop import FinalAnswerDecision, LoopControllerEvent
from klara.core.messages import KlaraMessage
from klara.core.tools import ToolResult


ResearchMode = Literal["off", "quick", "deep"]
ResearchStatus = Literal[
    "idle",
    "web_required",
    "searching",
    "fetching",
    "verifying",
    "need_more_search",
    "need_more_fetch",
    "ready",
    "budget_exhausted",
]


@dataclass
class WebResearchBudget:
    """Bound generic research work without hiding a nested search loop."""

    max_search_calls: int = 6
    max_fetch_calls: int = 12
    min_fetched_sources: int = 2
    min_independent_domains: int = 2
    max_candidate_results: int = 40


@dataclass
class WebResearchState:
    """Replayable public state for one web-backed run."""

    active: bool = False
    mode: ResearchMode = "off"
    status: ResearchStatus = "idle"
    goal: str = ""
    now_utc: str = ""
    user_timezone: str = ""
    searched_queries: list[str] = field(default_factory=list)
    fetched_source_ids: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    runtime_feedback: str = ""
    budget: WebResearchBudget = field(default_factory=WebResearchBudget)


@dataclass
class SearchCandidate:
    """One search result candidate that must be fetched before citation."""

    candidate_id: str
    search_id: str
    query: str
    title: str
    url: str
    canonical_url: str
    snippet: str
    provider: str
    rank: int
    published_at: str | None = None
    freshness_enforced: bool = False
    source_type: str = "unknown"
    fetched: bool = False


@dataclass
class SourceRecord:
    """One fetched source with generic quality and linkage signals."""

    source_id: str
    candidate_id: str | None
    url: str
    final_url: str
    title: str
    fetched_at: str
    text_preview: str
    relevant_snippets: list[str]
    extraction_quality: float
    no_relevant_terms_found: bool
    trust: str = "untrusted_external_content"


@dataclass(frozen=True)
class ResearchDecision:
    """Decision from generic evidence readiness policy."""

    ready: bool
    status: ResearchStatus
    gaps: tuple[str, ...] = ()
    next_hint: str = ""
    reason: str = ""


@dataclass
class EvidenceLedger:
    """Track candidate search cards separately from fetched source evidence."""

    candidates: dict[str, SearchCandidate] = field(default_factory=dict)
    sources: dict[str, SourceRecord] = field(default_factory=dict)

    def record_search_observation(self, payload: dict[str, object]) -> list[SearchCandidate]:
        """Record candidates from a web_search observation."""

        search_id = _string(payload.get("search_id")) or _stable_id(
            "search",
            _string(payload.get("provider")),
            _string(payload.get("query")),
        )
        query = _string(payload.get("original_query")) or _string(payload.get("query"))
        provider = _string(payload.get("provider")) or "unknown"
        freshness_enforced = bool(payload.get("freshness_enforced", False))
        recorded: list[SearchCandidate] = []
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            return recorded
        for index, raw in enumerate(raw_results, start=1):
            if not isinstance(raw, dict):
                continue
            url = _string(raw.get("url"))
            canonical_url = _canonical_url(_string(raw.get("canonical_url")) or url)
            if not canonical_url:
                continue
            candidate_id = _string(raw.get("candidate_id")) or _stable_id(
                "cand",
                search_id,
                str(index),
                canonical_url,
            )
            candidate = SearchCandidate(
                candidate_id=candidate_id,
                search_id=search_id,
                query=query,
                title=_compact(_string(raw.get("title")), max_chars=180),
                url=url,
                canonical_url=canonical_url,
                snippet=_compact(_string(raw.get("snippet")), max_chars=360),
                provider=provider,
                rank=_int(raw.get("rank")) or index,
                published_at=_string(raw.get("published_at")) or None,
                freshness_enforced=freshness_enforced,
                source_type=_string(raw.get("source_type")) or "unknown",
                fetched=self._is_url_fetched(canonical_url),
            )
            self.candidates[candidate_id] = candidate
            recorded.append(candidate)
        return recorded

    def record_fetch_observation(self, payload: dict[str, object]) -> SourceRecord | None:
        """Record a fetched source from a web_fetch observation."""

        url = _string(payload.get("url"))
        final_url = _string(payload.get("final_url")) or url
        canonical_url = _canonical_url(final_url)
        if not canonical_url:
            return None
        source_id = _string(payload.get("source_id")) or _stable_id("src", canonical_url)
        candidate_id = _string(payload.get("candidate_id")) or self._candidate_id_for_url(
            canonical_url
        )
        quality_payload = payload.get("extraction_quality")
        quality_score = 0.0
        if isinstance(quality_payload, dict):
            quality_score = _float(quality_payload.get("score"))
        text = _string(payload.get("text"))
        snippets = _snippets_from_text(text)
        record = SourceRecord(
            source_id=source_id,
            candidate_id=candidate_id or None,
            url=url,
            final_url=final_url,
            title=_compact(_string(payload.get("title")), max_chars=180),
            fetched_at=_string(payload.get("fetched_at")) or _now_iso(),
            text_preview=_compact(text, max_chars=700),
            relevant_snippets=snippets,
            extraction_quality=quality_score,
            no_relevant_terms_found=bool(payload.get("no_relevant_terms_found", False)),
            trust=_string(payload.get("trust")) or "untrusted_external_content",
        )
        self.sources[source_id] = record
        self._mark_candidate_fetched(candidate_id, canonical_url)
        return record

    def fetched_source_count(self) -> int:
        """Return number of fetched source records."""

        return len(self.sources)

    def good_sources(self) -> tuple[SourceRecord, ...]:
        """Return fetched sources that satisfy generic readability relevance."""

        return tuple(
            source
            for source in self.sources.values()
            if source.extraction_quality >= 0.45 and not source.no_relevant_terms_found
        )

    def independent_domain_count(self) -> int:
        """Return count of independent domains among good fetched sources."""

        domains = {
            _domain(source.final_url or source.url)
            for source in self.good_sources()
            if _domain(source.final_url or source.url)
        }
        return len(domains)

    def search_call_count(self) -> int:
        """Return count of unique search observations recorded."""

        return len({candidate.search_id for candidate in self.candidates.values()})

    def fetch_call_count(self) -> int:
        """Return count of fetched source records."""

        return len(self.sources)

    def top_unfetched_candidates(self, limit: int = 5) -> tuple[SearchCandidate, ...]:
        """Return top unfetched candidates in provider rank order."""

        candidates = sorted(
            (candidate for candidate in self.candidates.values() if not candidate.fetched),
            key=lambda candidate: (candidate.search_id, candidate.rank),
        )
        return tuple(candidates[:limit])

    def recent_sources(self, limit: int = 4) -> tuple[SourceRecord, ...]:
        """Return most recently recorded sources."""

        return tuple(list(self.sources.values())[-limit:])

    def compact_state(self) -> dict[str, object]:
        """Return a JSON-compatible prompt/trace summary."""

        return {
            "candidate_count": len(self.candidates),
            "fetched_source_count": self.fetched_source_count(),
            "good_source_count": len(self.good_sources()),
            "independent_domain_count": self.independent_domain_count(),
            "top_unfetched_candidates": [
                _candidate_summary(candidate)
                for candidate in self.top_unfetched_candidates(limit=6)
            ],
            "recent_fetched_sources": [
                _source_summary(source) for source in self.recent_sources(limit=5)
            ],
        }

    def _is_url_fetched(self, canonical_url: str) -> bool:
        return any(
            _canonical_url(source.final_url or source.url) == canonical_url
            for source in self.sources.values()
        )

    def _candidate_id_for_url(self, canonical_url: str) -> str:
        for candidate in self.candidates.values():
            if candidate.canonical_url == canonical_url:
                return candidate.candidate_id
        return ""

    def _mark_candidate_fetched(self, candidate_id: str, canonical_url: str) -> None:
        for key, candidate in tuple(self.candidates.items()):
            if candidate.candidate_id == candidate_id or candidate.canonical_url == canonical_url:
                self.candidates[key] = SearchCandidate(
                    candidate_id=candidate.candidate_id,
                    search_id=candidate.search_id,
                    query=candidate.query,
                    title=candidate.title,
                    url=candidate.url,
                    canonical_url=candidate.canonical_url,
                    snippet=candidate.snippet,
                    provider=candidate.provider,
                    rank=candidate.rank,
                    published_at=candidate.published_at,
                    freshness_enforced=candidate.freshness_enforced,
                    source_type=candidate.source_type,
                    fetched=True,
                )


class WebResearchPolicy:
    """Evaluate generic web evidence readiness without domain rules."""

    def evaluate(
        self,
        *,
        state: WebResearchState,
        ledger: EvidenceLedger,
    ) -> ResearchDecision:
        """Return whether current evidence is ready for finalization."""

        if not state.active:
            return ResearchDecision(ready=True, status="idle", reason="web_off")
        if _budget_exhausted(state=state, ledger=ledger):
            return ResearchDecision(
                ready=True,
                status="budget_exhausted",
                gaps=tuple(state.gaps),
                next_hint=(
                    "Answer only from fetched evidence already in the transcript. "
                    "State any uncertainty from budget exhaustion."
                ),
                reason="budget_exhausted",
            )
        if ledger.fetched_source_count() == 0:
            return ResearchDecision(
                ready=False,
                status="need_more_fetch" if ledger.candidates else "need_more_search",
                gaps=("Need at least one fetched source before answering.",),
                next_hint=_next_hint_for_no_sources(ledger),
                reason="no_fetched_sources",
            )
        good_sources = ledger.good_sources()
        if not good_sources:
            return ResearchDecision(
                ready=False,
                status="need_more_search",
                gaps=("Fetched pages were low quality or did not match the request.",),
                next_hint=(
                    "Call web_search with a narrower query or a different source angle, "
                    "then fetch a relevant candidate before answering."
                ),
                reason="low_quality_sources",
            )
        if len(good_sources) < state.budget.min_fetched_sources:
            return ResearchDecision(
                ready=False,
                status="need_more_fetch",
                gaps=(
                    f"Need {state.budget.min_fetched_sources} good fetched sources; "
                    f"have {len(good_sources)}.",
                ),
                next_hint="Call web_fetch on another relevant candidate URL before finalizing.",
                reason="need_more_sources",
            )
        domain_count = ledger.independent_domain_count()
        if domain_count < state.budget.min_independent_domains:
            return ResearchDecision(
                ready=False,
                status="need_more_search",
                gaps=(
                    f"Need {state.budget.min_independent_domains} independent domains; "
                    f"have {domain_count}.",
                ),
                next_hint=(
                    "Call web_search or web_fetch for an independent domain before "
                    "finalizing."
                ),
                reason="need_independent_sources",
            )
        return ResearchDecision(
            ready=True,
            status="ready",
            next_hint="Evidence is ready. Answer from fetched sources only.",
            reason="ready",
        )


class WebResearchController:
    """Loop controller that keeps web research evidence generic and replayable."""

    def __init__(
        self,
        *,
        user_timezone: str = "local",
        policy: WebResearchPolicy | None = None,
    ) -> None:
        """Create an empty controller for one run."""

        self.user_timezone = user_timezone
        self.state = WebResearchState(user_timezone=user_timezone)
        self.ledger = EvidenceLedger()
        self.policy = policy or WebResearchPolicy()
        self._events: list[LoopControllerEvent] = []
        self._run_id = ""
        self._last_decision = ResearchDecision(ready=True, status="idle", reason="web_off")
        self._compacted_tool_ids: set[str] = set()

    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        """Initialize state for one run from the user request."""

        self._run_id = run_id
        mode = _classify_mode(user_input)
        self.state = WebResearchState(
            active=mode != "off",
            mode=mode,
            status="web_required" if mode != "off" else "idle",
            goal=_compact(_strip_timestamp_envelope(user_input), max_chars=220),
            now_utc=_now_iso(),
            user_timezone=self.user_timezone,
            budget=_budget_for_mode(mode),
        )
        self.ledger = EvidenceLedger()
        self._compacted_tool_ids = set()
        if not self.state.active:
            return
        self._queue(
            "web_research.started",
            {
                "mode": self.state.mode,
                "status": self.state.status,
                "goal_preview": self.state.goal,
                "now_utc": self.state.now_utc,
                "user_timezone": self.user_timezone,
                "budget": self._budget_payload(),
            },
        )
        self._evaluate_and_trace(reason="run_started")

    def system_prompt_suffix(self) -> str:
        """Return compact model-visible web research state."""

        if not self.state.active:
            return ""
        state = self.state
        ledger_state = self.ledger.compact_state()
        lines = [
            "<web_research_runtime>",
            f"status: {state.status}",
            f"mode: {state.mode}",
            f"goal: {state.goal}",
            f"now_utc: {state.now_utc}",
            f"user_timezone: {state.user_timezone}",
            "",
            "rules:",
            "- Search result snippets are candidate leads, not final evidence.",
            "- Use web_fetch on relevant candidate URLs before factual claims.",
            "- Prefer fetched sources over search snippets.",
            "- Do not cite or rely on a source that was only seen as a search candidate.",
            "- If evidence is incomplete and budget remains, continue searching/fetching.",
            "- If budget is exhausted, answer from fetched evidence and mark uncertainty.",
            "",
            "progress:",
            f"- searched_queries: {json.dumps(state.searched_queries[-5:], ensure_ascii=False)}",
            f"- fetched_source_count: {ledger_state['fetched_source_count']}",
            f"- good_source_count: {ledger_state['good_source_count']}",
            f"- independent_domain_count: {ledger_state['independent_domain_count']}",
        ]
        if state.gaps:
            lines.extend(["", "remaining_gaps:"])
            lines.extend(f"- {gap}" for gap in state.gaps[:4])
        if self._last_decision.next_hint:
            lines.extend(["", "next_hint:", self._last_decision.next_hint])
        top_candidates = ledger_state["top_unfetched_candidates"]
        if isinstance(top_candidates, list) and top_candidates:
            lines.extend(["", "top_unfetched_candidates:"])
            lines.extend(f"- {_format_candidate_line(item)}" for item in top_candidates[:5])
        recent_sources = ledger_state["recent_fetched_sources"]
        if isinstance(recent_sources, list) and recent_sources:
            lines.extend(["", "recent_fetched_sources:"])
            lines.extend(f"- {_format_source_line(item)}" for item in recent_sources[:4])
        if state.runtime_feedback:
            lines.extend(["", "runtime_feedback:", state.runtime_feedback])
        lines.append("</web_research_runtime>")
        return "\n".join(lines)

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        """Record web tool observations and update readiness state."""

        changed = False
        for result in results:
            payload = _json_object(result.content)
            if result.name == "web_search" and result.ok:
                self.state.status = "searching"
                before = len(self.ledger.candidates)
                candidates = self.ledger.record_search_observation(payload)
                query = _string(payload.get("original_query")) or _string(payload.get("query"))
                if query and query not in self.state.searched_queries:
                    self.state.searched_queries.append(query)
                for candidate in candidates:
                    self._queue("evidence.candidate_recorded", _candidate_summary(candidate))
                changed = changed or len(self.ledger.candidates) != before
                self._queue(
                    "web_search.completed",
                    {
                        "search_id": payload.get("search_id"),
                        "query_preview": _compact(query, max_chars=160),
                        "provider": payload.get("provider"),
                        "result_count": payload.get("result_count"),
                        "freshness_enforced": payload.get("freshness_enforced"),
                    },
                )
            elif result.name == "web_fetch" and result.ok:
                self.state.status = "fetching"
                source = self.ledger.record_fetch_observation(payload)
                if source is not None:
                    if source.source_id not in self.state.fetched_source_ids:
                        self.state.fetched_source_ids.append(source.source_id)
                    changed = True
                    self._queue("evidence.source_recorded", _source_summary(source))
                    self._queue(
                        "web_fetch.completed",
                        {
                            "source_id": source.source_id,
                            "candidate_id": source.candidate_id,
                            "quality": source.extraction_quality,
                            "text_length": len(source.text_preview),
                            "no_relevant_terms_found": source.no_relevant_terms_found,
                        },
                    )
        if changed:
            self._evaluate_and_trace(reason="tool_results")

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        """Block premature no-tool answers while research budget remains."""

        if not self.state.active:
            return FinalAnswerDecision(allowed=True, reason="web_off")
        decision = self._evaluate_and_trace(reason="before_final_answer")
        if decision.ready:
            return FinalAnswerDecision(
                allowed=True,
                reason=decision.reason or decision.status,
                feedback=decision.next_hint,
            )
        feedback = _final_block_feedback(decision)
        self.state.runtime_feedback = feedback
        return FinalAnswerDecision(
            allowed=False,
            reason=decision.reason or decision.status,
            feedback=feedback,
        )

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        """Compact older web tool observations for the next model turn."""

        if not self.state.active:
            return messages
        prepared = list(messages)
        web_fetch_indices = [
            index
            for index, message in enumerate(prepared)
            if message.role == "tool" and message.name == "web_fetch"
        ]
        keep_full = set(web_fetch_indices[-2:])
        compacted = 0
        for index in web_fetch_indices:
            if index in keep_full:
                continue
            message = prepared[index]
            if not message.tool_call_id or message.tool_call_id in self._compacted_tool_ids:
                continue
            compacted_content = _compact_tool_observation(message.content)
            if compacted_content == message.content:
                continue
            prepared[index] = KlaraMessage(
                role=message.role,
                content=compacted_content,
                name=message.name,
                tool_call_id=message.tool_call_id,
            )
            self._compacted_tool_ids.add(message.tool_call_id)
            compacted += 1
        if compacted:
            self._queue(
                "context.compacted",
                {
                    "compacted_messages": compacted,
                    "strategy": "older_web_fetch_to_source_summary",
                },
            )
        return prepared

    def drain_events(self) -> tuple[LoopControllerEvent, ...]:
        """Return pending trace events from web research state."""

        events = tuple(self._events)
        self._events.clear()
        return events

    def _evaluate_and_trace(self, *, reason: str) -> ResearchDecision:
        decision = self.policy.evaluate(state=self.state, ledger=self.ledger)
        self._last_decision = decision
        self.state.status = decision.status
        self.state.gaps = list(decision.gaps)
        if decision.ready:
            self.state.runtime_feedback = ""
        self._queue(
            "evidence.readiness_evaluated",
            {
                "reason": reason,
                "ready": decision.ready,
                "status": decision.status,
                "decision_reason": decision.reason,
                "gaps": list(decision.gaps),
                "next_hint": decision.next_hint,
                "budget": self._budget_payload(),
                "ledger": self.ledger.compact_state(),
            },
        )
        self._queue(
            "web_research.state_updated",
            {
                "mode": self.state.mode,
                "status": self.state.status,
                "searched_queries": list(self.state.searched_queries[-8:]),
                "fetched_source_ids": list(self.state.fetched_source_ids[-8:]),
                "gaps": list(self.state.gaps),
                "budget": self._budget_payload(),
            },
        )
        return decision

    def _budget_payload(self) -> dict[str, object]:
        budget = self.state.budget
        return {
            "max_search_calls": budget.max_search_calls,
            "max_fetch_calls": budget.max_fetch_calls,
            "min_fetched_sources": budget.min_fetched_sources,
            "min_independent_domains": budget.min_independent_domains,
            "max_candidate_results": budget.max_candidate_results,
            "search_calls": self.ledger.search_call_count(),
            "fetch_calls": self.ledger.fetch_call_count(),
        }

    def _queue(self, event_type: str, payload: dict[str, object]) -> None:
        self._events.append(LoopControllerEvent(type=event_type, payload=payload))


def _budget_for_mode(mode: ResearchMode) -> WebResearchBudget:
    if mode == "deep":
        return WebResearchBudget(
            max_search_calls=8,
            max_fetch_calls=16,
            min_fetched_sources=3,
            min_independent_domains=2,
        )
    if mode == "quick":
        return WebResearchBudget(
            max_search_calls=3,
            max_fetch_calls=5,
            min_fetched_sources=1,
            min_independent_domains=1,
        )
    return WebResearchBudget(
        max_search_calls=0,
        max_fetch_calls=0,
        min_fetched_sources=0,
        min_independent_domains=0,
    )


def _budget_exhausted(*, state: WebResearchState, ledger: EvidenceLedger) -> bool:
    return (
        ledger.search_call_count() >= state.budget.max_search_calls
        and ledger.fetch_call_count() >= state.budget.max_fetch_calls
    )


def _next_hint_for_no_sources(ledger: EvidenceLedger) -> str:
    candidate = next(iter(ledger.top_unfetched_candidates(limit=1)), None)
    if candidate is None:
        return "Call web_search with a focused query for relevant public sources before answering."
    return (
        "Call web_fetch on a relevant candidate before answering, such as "
        f"{candidate.candidate_id} ({_domain(candidate.url)})."
    )


def _final_block_feedback(decision: ResearchDecision) -> str:
    parts = [
        "Web research is not ready for a final factual answer.",
        f"Reason: {decision.reason or decision.status}.",
    ]
    if decision.gaps:
        parts.append("Gaps: " + "; ".join(decision.gaps))
    if decision.next_hint:
        parts.append("Next: " + decision.next_hint)
    return " ".join(parts)


def _classify_mode(user_input: str) -> ResearchMode:
    compact = _strip_timestamp_envelope(user_input).lower()
    deep_terms = (
        "research",
        "compare",
        "comparison",
        "comprehensive",
        "report",
        "multi-source",
        "multiple sources",
        "detailed",
        "深入",
        "研究",
        "比较",
        "对比",
        "详细",
        "多来源",
        "报告",
        "整理",
        "总结",
    )
    quick_terms = (
        "search",
        "look up",
        "latest",
        "current",
        "today",
        "news",
        "schedule",
        "score",
        "scores",
        "price",
        "version",
        "release",
        "查",
        "搜索",
        "搜",
        "最新",
        "最近",
        "当前",
        "现在",
        "今天",
        "新闻",
        "赛程",
        "比分",
        "价格",
        "版本",
        "联网",
    )
    if any(term in compact for term in deep_terms):
        return "deep"
    if any(term in compact for term in quick_terms):
        return "quick"
    return "off"


def _strip_timestamp_envelope(text: str) -> str:
    return re.sub(r"<runtime_context>.*?</runtime_context>", "", text, flags=re.S).strip()


def _json_object(text: str) -> dict[str, object]:
    if not text.strip().startswith("{"):
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _compact_tool_observation(content: str) -> str:
    payload = _json_object(content)
    if payload.get("observation_kind") != "web_fetched_source":
        return content
    compacted = {
        "observation_kind": "web_fetched_source_compacted",
        "source_id": payload.get("source_id"),
        "candidate_id": payload.get("candidate_id"),
        "title": payload.get("title"),
        "final_url": payload.get("final_url"),
        "fetched_at": payload.get("fetched_at"),
        "relevant_snippets": _snippets_from_text(_string(payload.get("text"))),
        "extraction_quality": payload.get("extraction_quality"),
        "no_relevant_terms_found": payload.get("no_relevant_terms_found"),
        "trust": payload.get("trust"),
    }
    return json.dumps(compacted, ensure_ascii=False, sort_keys=True)


def _candidate_summary(candidate: SearchCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "search_id": candidate.search_id,
        "title": candidate.title,
        "domain": _domain(candidate.url),
        "rank": candidate.rank,
        "snippet_preview": _compact(candidate.snippet, max_chars=180),
        "fetched": candidate.fetched,
        "must_fetch_before_citing": True,
    }


def _source_summary(source: SourceRecord) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "candidate_id": source.candidate_id,
        "title": source.title,
        "domain": _domain(source.final_url or source.url),
        "quality": source.extraction_quality,
        "no_relevant_terms_found": source.no_relevant_terms_found,
        "text_preview": _compact(source.text_preview, max_chars=220),
    }


def _format_candidate_line(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    return " | ".join(
        [
            _string(item.get("candidate_id")),
            _string(item.get("title")),
            _string(item.get("domain")),
            _string(item.get("snippet_preview")),
        ]
    )


def _format_source_line(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    return " | ".join(
        [
            _string(item.get("source_id")),
            _string(item.get("title")),
            _string(item.get("domain")),
            f"quality={_string(item.get('quality'))}",
        ]
    )


def _snippets_from_text(text: str) -> list[str]:
    compact = _compact(text, max_chars=900)
    if not compact:
        return []
    parts = [part.strip() for part in compact.split("---") if part.strip()]
    return parts[:4] if parts else [compact]


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    netloc = parsed.hostname.lower()
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower()


def _stable_id(prefix: str, *parts: str) -> str:
    import hashlib

    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return 0.0


def _compact(text: str, *, max_chars: int) -> str:
    return " ".join(text.split())[:max_chars]
