from __future__ import annotations

import json

from klara.core.messages import KlaraMessage
from klara.core.tools import ToolResult
from klara.services.web import WebResearchBudget, WebResearchController


def test_current_information_request_activates_web_research() -> None:
    controller = WebResearchController(user_timezone="Asia/Shanghai")

    controller.on_run_start(user_input="What are the latest OpenAI SDK changes?", run_id="run-web")

    assert controller.state.active is True
    assert controller.state.mode == "quick"
    assert controller.state.status in {"web_required", "need_more_search"}
    suffix = controller.system_prompt_suffix()
    assert "<web_research_runtime>" in suffix
    assert "Search result snippets are candidate leads" in suffix
    event_types = [event.type for event in controller.drain_events()]
    assert "web_research.started" in event_types
    assert "evidence.readiness_evaluated" in event_types


def test_exact_time_request_uses_clock_tool_without_web_research() -> None:
    controller = WebResearchController(user_timezone="Asia/Shanghai")

    controller.on_run_start(
        user_input=(
            "\u8bf7\u8c03\u7528 current_time \u5de5\u5177\u67e5\u8be2"
            "\u4e0a\u6d77\u5f53\u524d\u65f6\u95f4\uff0c\u7136\u540e"
            "\u4e00\u53e5\u8bdd\u56de\u7b54\u3002"
        ),
        run_id="run-clock",
    )

    assert controller.state.active is False
    assert controller.system_prompt_suffix() == ""
    decision = controller.before_final_answer(content="上海当前时间是 14:05。")
    assert decision.allowed is True
    assert decision.reason == "web_off"
    assert controller.drain_events() == ()


def test_today_event_request_still_activates_web_research() -> None:
    controller = WebResearchController(user_timezone="Asia/Shanghai")

    controller.on_run_start(
        user_input=(
            "\u4eca\u5929\u4e16\u754c\u676f\u6700\u65b0"
            "\u8d5b\u7a0b\u600e\u4e48\u6837\uff1f"
        ),
        run_id="run-today-web",
    )

    assert controller.state.active is True
    assert controller.state.mode == "quick"
    assert "web_research.started" in [event.type for event in controller.drain_events()]


def test_stable_chat_leaves_web_research_off() -> None:
    controller = WebResearchController()

    controller.on_run_start(user_input="hello, introduce yourself", run_id="run-stable")

    assert controller.state.active is False
    assert controller.system_prompt_suffix() == ""
    assert controller.before_final_answer(content="hello").allowed is True
    assert controller.drain_events() == ()


def test_search_only_observation_blocks_final_answer() -> None:
    controller = WebResearchController()
    controller.on_run_start(user_input="look up the latest schedule", run_id="run-search-only")
    controller.drain_events()
    controller.on_tool_results(
        results=(
            ToolResult(
                tool_call_id="call-search",
                name="web_search",
                content=json.dumps(
                    {
                        "observation_kind": "web_search_candidates",
                        "search_id": "search_1",
                        "query": "latest schedule",
                        "provider": "duckduckgo_lite",
                        "freshness_enforced": False,
                        "results": [
                            {
                                "candidate_id": "cand_1",
                                "title": "Schedule",
                                "url": "https://example.com/schedule",
                                "canonical_url": "https://example.com/schedule",
                                "snippet": "Candidate only",
                                "rank": 1,
                            }
                        ],
                    }
                ),
            ),
        )
    )

    decision = controller.before_final_answer(content="Here is the schedule.")

    assert decision.allowed is False
    assert decision.reason == "no_fetched_sources"
    assert "before answering" in decision.feedback
    events = controller.drain_events()
    assert any(event.type == "evidence.candidate_recorded" for event in events)
    assert any(
        event.type == "evidence.readiness_evaluated"
        and event.payload["ready"] is False
        for event in events
    )


def test_empty_search_budget_allows_uncertain_final_answer() -> None:
    controller = WebResearchController()
    controller.on_run_start(user_input="look up the latest schedule", run_id="run-empty-search")
    controller.state.budget = WebResearchBudget(
        max_search_calls=1,
        max_fetch_calls=5,
        min_fetched_sources=1,
        min_independent_domains=1,
    )
    controller.drain_events()
    controller.on_tool_results(
        results=(
            ToolResult(
                tool_call_id="call-search",
                name="web_search",
                content=json.dumps(
                    {
                        "observation_kind": "web_search_candidates",
                        "search_id": "search_1",
                        "query": "latest schedule",
                        "provider": "duckduckgo_lite",
                        "result_count": 0,
                        "results": [],
                    }
                ),
            ),
        )
    )

    decision = controller.before_final_answer(content="I have no fetched sources.")

    assert decision.allowed is True
    assert decision.reason == "budget_exhausted"
    assert "uncertainty" in decision.feedback
    events = controller.drain_events()
    assert any(
        event.type == "evidence.readiness_evaluated"
        and event.payload["budget"]["search_calls"] == 1
        for event in events
    )


def test_failed_search_attempt_can_exhaust_web_progress() -> None:
    controller = WebResearchController()
    controller.on_run_start(user_input="look up the latest schedule", run_id="run-search-fail")
    controller.state.budget = WebResearchBudget(
        max_search_calls=1,
        max_fetch_calls=5,
        min_fetched_sources=1,
        min_independent_domains=1,
    )
    controller.drain_events()
    controller.on_tool_results(
        results=(
            ToolResult(
                tool_call_id="call-search",
                name="web_search",
                content="",
                ok=False,
                error="Provider returned a challenge page.",
            ),
        )
    )

    decision = controller.before_final_answer(content="Search failed.")

    assert decision.allowed is True
    assert decision.reason == "budget_exhausted"
    events = controller.drain_events()
    assert any(event.type == "web_search.failed" for event in events)
    assert any(
        event.type == "evidence.readiness_evaluated"
        and event.payload["budget"]["search_calls"] == 1
        for event in events
    )


def test_good_fetched_source_allows_quick_final_answer() -> None:
    controller = WebResearchController()
    controller.on_run_start(user_input="What changed in the latest Python release?", run_id="run-fetch")
    controller.drain_events()
    controller.on_tool_results(
        results=(
            ToolResult(
                tool_call_id="call-fetch",
                name="web_fetch",
                content=json.dumps(
                    {
                        "observation_kind": "web_fetched_source",
                        "source_id": "src_1",
                        "candidate_id": "cand_1",
                        "url": "https://docs.python.org/release",
                        "final_url": "https://docs.python.org/release",
                        "title": "Python release notes",
                        "text": "Python release notes include current version changes.",
                        "extraction_quality": {
                            "score": 0.88,
                            "has_relevant_terms": True,
                        },
                        "no_relevant_terms_found": False,
                        "fetched_at": "2026-06-23T00:00:00Z",
                    }
                ),
            ),
        )
    )

    decision = controller.before_final_answer(content="Python changed...")

    assert decision.allowed is True
    assert decision.reason == "ready"


def test_deep_research_requires_multiple_good_sources() -> None:
    controller = WebResearchController()
    controller.on_run_start(user_input="Compare two latest AI agent projects in a detailed report", run_id="run-deep")
    controller.drain_events()
    controller.on_tool_results(
        results=(
            ToolResult(
                tool_call_id="call-fetch",
                name="web_fetch",
                content=json.dumps(
                    {
                        "observation_kind": "web_fetched_source",
                        "source_id": "src_1",
                        "url": "https://example.com/agent",
                        "final_url": "https://example.com/agent",
                        "title": "Agent report",
                        "text": "Agent project comparison details.",
                        "extraction_quality": {"score": 0.9},
                        "no_relevant_terms_found": False,
                        "fetched_at": "2026-06-23T00:00:00Z",
                    }
                ),
            ),
        )
    )

    decision = controller.before_final_answer(content="Comparison...")

    assert controller.state.mode == "deep"
    assert decision.allowed is False
    assert decision.reason == "need_more_sources"


def test_budget_exhaustion_allows_uncertain_final_answer() -> None:
    controller = WebResearchController()
    controller.on_run_start(user_input="look up the latest news", run_id="run-budget")
    controller.state.budget = WebResearchBudget(
        max_search_calls=0,
        max_fetch_calls=0,
        min_fetched_sources=1,
        min_independent_domains=1,
    )

    decision = controller.before_final_answer(content="I have partial evidence.")

    assert decision.allowed is True
    assert decision.reason == "budget_exhausted"
    assert "uncertainty" in decision.feedback


def test_prepare_next_turn_compacts_older_web_fetch_messages() -> None:
    controller = WebResearchController()
    controller.on_run_start(user_input="give me a detailed latest source summary", run_id="run-compact")
    full_payload = {
        "observation_kind": "web_fetched_source",
        "source_id": "src_old",
        "candidate_id": "cand_old",
        "title": "Old source",
        "final_url": "https://example.com/old",
        "fetched_at": "2026-06-23T00:00:00Z",
        "text": "Old source text. " * 200,
        "extraction_quality": {"score": 0.8},
        "no_relevant_terms_found": False,
        "trust": "untrusted_external_content",
    }
    messages = [
        KlaraMessage(role="user", content="latest"),
        KlaraMessage(role="tool", name="web_fetch", tool_call_id="old", content=json.dumps(full_payload)),
        KlaraMessage(role="tool", name="web_fetch", tool_call_id="new-1", content=json.dumps({**full_payload, "source_id": "src_new_1"})),
        KlaraMessage(role="tool", name="web_fetch", tool_call_id="new-2", content=json.dumps({**full_payload, "source_id": "src_new_2"})),
    ]

    prepared = controller.prepare_next_turn(messages)

    compacted = json.loads(prepared[1].content)
    assert compacted["observation_kind"] == "web_fetched_source_compacted"
    assert compacted["source_id"] == "src_old"
    assert "text" not in compacted
    assert json.loads(prepared[2].content)["observation_kind"] == "web_fetched_source"
    assert json.loads(prepared[3].content)["observation_kind"] == "web_fetched_source"
