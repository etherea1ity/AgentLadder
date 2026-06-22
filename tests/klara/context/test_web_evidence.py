from __future__ import annotations

from datetime import date
import json

from klara.context.web_evidence import WebEvidenceGuard
from klara.core.messages import KlaraMessage


def test_current_world_cup_search_requires_fetch_before_answer() -> None:
    """Search candidates should not support current sports facts by themselves."""

    messages = (
        user("latest World Cup scores"),
        tool(
            "web_search",
            {
                "evidence_status": "candidate_snippets_only",
                "results": [
                    {
                        "title": "Reuters report",
                        "url": "https://www.reuters.com/sports/soccer/world-cup-report",
                        "source_quality": "wire",
                    }
                ],
            },
        ),
        assistant("England beat Croatia 4-2."),
    )

    guarded = WebEvidenceGuard(current_date=date(2026, 6, 18)).apply(messages)

    assert guarded is not None
    assert "<runtime_tool_guard>" in guarded[-1].content


def test_aggregator_only_evidence_blocks_concrete_score_answer() -> None:
    """Aggregator-only fetched evidence should not support concrete scores."""

    messages = (
        user("latest World Cup scores"),
        tool(
            "web_fetch",
            {
                "url": "https://www.fifawatch.com/world-cup-live",
                "source_quality": "aggregator",
                "text": "England 4-2 Croatia",
            },
        ),
        assistant("England beat Croatia 4-2."),
    )

    guarded = WebEvidenceGuard(current_date=date(2026, 6, 18)).apply(messages)

    assert guarded is not None
    assert "<runtime_current_sports_evidence_guard>" in guarded[-1].content
    assert "Aggregator-only evidence is not enough" in guarded[-1].content


def test_fixture_only_evidence_blocks_fake_zero_zero_answer() -> None:
    """A scheduled fixture should not be converted into a 0-0 score."""

    messages = (
        user("today World Cup fixtures and scores"),
        tool(
            "web_fetch",
            {
                "url": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026",
                "source_quality": "official",
                "text": "June 18 fixture: England v Croatia, Dallas.",
            },
        ),
        assistant("England 0:0 Croatia."),
    )

    guarded = WebEvidenceGuard(current_date=date(2026, 6, 18)).apply(messages)

    assert guarded is not None
    assert "A scheduled match with no fetched verified score is not 0:0" in guarded[-1].content


def test_temporal_guard_catches_wrong_world_cup_start_date() -> None:
    """A June 18 start claim should be corrected when evidence says June 11."""

    messages = (
        user("latest World Cup news"),
        tool(
            "web_fetch",
            {
                "url": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026",
                "source_quality": "official",
                "text": "The FIFA World Cup opening match starts on June 11, 2026.",
            },
        ),
        assistant("The World Cup starts on June 18, 2026."),
    )

    guarded = WebEvidenceGuard(current_date=date(2026, 6, 18)).apply(messages)

    assert guarded is not None
    assert "<runtime_current_sports_evidence_guard>" in guarded[-1].content
    assert "Fixtures are not results" in guarded[-1].content


def test_fetched_reuters_score_can_support_specific_result() -> None:
    """A preferred fetched source can support a directly present score."""

    messages = (
        user("latest World Cup scores"),
        tool(
            "web_fetch",
            {
                "url": "https://www.reuters.com/sports/soccer/world-cup-report",
                "source_quality": "wire",
                "text": "England beat Croatia 4-2 in Dallas.",
            },
        ),
        KlaraMessage(
            role="user",
            content="<runtime_web_synthesis_guard>already checked</runtime_web_synthesis_guard>",
        ),
        assistant("England beat Croatia 4-2 in Dallas."),
    )

    assert WebEvidenceGuard(current_date=date(2026, 6, 18)).apply(messages) is None


def test_fetched_fifa_schedule_can_support_fixture_without_score() -> None:
    """Official fixture evidence can support scheduled items without fake scores."""

    messages = (
        user("today World Cup fixtures"),
        tool(
            "web_fetch",
            {
                "url": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026",
                "source_quality": "official",
                "text": "June 18 fixtures include Czechia v South Africa.",
            },
        ),
        KlaraMessage(
            role="user",
            content="<runtime_web_synthesis_guard>already checked</runtime_web_synthesis_guard>",
        ),
        assistant("June 18 fixtures include Czechia v South Africa; no verified score was fetched."),
    )

    assert WebEvidenceGuard(current_date=date(2026, 6, 18)).apply(messages) is None


def user(content: str) -> KlaraMessage:
    return KlaraMessage(role="user", content=content)


def assistant(content: str) -> KlaraMessage:
    return KlaraMessage(role="assistant", content=content)


def tool(name: str, payload: dict[str, object]) -> KlaraMessage:
    return KlaraMessage(role="tool", name=name, content=json.dumps(payload))
