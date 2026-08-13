from __future__ import annotations

import json

from klara.core.loop import KlaraLoop
from klara.core.messages import ModelResponse
from klara.core.policies import LoopPolicy
from klara.core.tools import JsonObject, ToolCall, ToolMetadata, ToolResult, ToolSpec
from klara.services.evidence import EvidenceRuntimeController
from klara.services.web import WebResearchController
from klara.tools.base import BaseTool
from klara.tools.builtin.evidence_submit.tool import EvidenceSubmitTool
from klara.tools.executor import ToolExecutor


class _ScriptedLlm:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses

    def complete(self, **_: object) -> ModelResponse:
        return self.responses.pop(0)


class _FixedFetchTool(BaseTool):
    spec = ToolSpec(name="web_fetch", description="fixture", input_schema={"type": "object"})
    metadata = ToolMetadata(label="Fixture fetch", category="test")

    def run(self, arguments: JsonObject) -> ToolResult:
        result = _fetch()
        return ToolResult(
            tool_call_id=self.call_id(arguments),
            name=result.name,
            content=result.content,
        )


def _fetch(*, status: str = "admissible") -> ToolResult:
    return ToolResult(
        tool_call_id="fetch-1",
        name="web_fetch",
        content=json.dumps(
            {
                "observation_kind": "web_fetched_source",
                "source_id": "src-1",
                "url": "https://docs.example.test/release",
                "final_url": "https://docs.example.test/release",
                "title": "Release notes",
                "text": "Version 4 ships evidence control and bounded verification.",
                "extraction_quality": {"score": 0.9},
                "no_relevant_terms_found": False,
                "fetched_at": "2026-08-13T00:00:00+00:00",
                "evidence_status": status,
            }
        ),
    )


def _submission(
    *, judgment: str = "supported", source_id: str = "src-1", witness: str = "Version 4 ships evidence control"
) -> ToolResult:
    return ToolResult(
        tool_call_id="submit-1",
        name="evidence_submit",
        content=json.dumps(
            {
                "final_text": "Version 4 adds evidence control.",
                "claims": [
                    {"claim_id": "claim-1", "text": "Version 4 adds evidence control.", "required": True}
                ],
                "links": [
                    {
                        "claim_id": "claim-1",
                        "source_id": source_id,
                        "judgment": judgment,
                        "support_note": witness,
                    }
                ],
                "citations": [{"claim_id": "claim-1", "source_id": source_id}],
                "abstain": False,
            }
        ),
    )


def _active_controllers() -> tuple[WebResearchController, EvidenceRuntimeController]:
    web = WebResearchController()
    evidence = EvidenceRuntimeController(web)
    web.on_run_start(user_input="What changed in the latest release?", run_id="run-1")
    evidence.on_run_start(user_input="What changed in the latest release?", run_id="run-1")
    web.drain_events()
    return web, evidence


def test_real_runtime_requires_submission_and_renders_fetched_source() -> None:
    web, evidence = _active_controllers()
    web.on_tool_results(results=(_fetch(),))

    missing = evidence.before_final_answer(content="unsupported prose")
    assert missing.allowed is False
    assert missing.reason == "evidence_submission_required"

    evidence.on_tool_results(results=(_submission(),))
    decision = evidence.before_final_answer(content="ignored model prose")

    assert decision.allowed is True
    assert decision.reason == "evidence_verified"
    assert "Version 4 adds evidence control." in (decision.replacement_content or "")
    assert "[Release notes](https://docs.example.test/release)" in (
        decision.replacement_content or ""
    )
    events = evidence.drain_events()
    assert events[-1].type == "evidence.verification_completed"
    assert events[-1].payload["selected_source_ids"] == ["src-1"]


def test_candidate_source_id_and_non_exact_witness_are_rejected() -> None:
    web, evidence = _active_controllers()
    web.on_tool_results(results=(_fetch(),))
    evidence.on_tool_results(results=(_submission(source_id="cand-1"),))
    dangling = evidence.before_final_answer(content="answer")
    assert dangling.allowed is False
    assert dangling.reason == "invalid_evidence_graph"

    evidence.on_tool_results(results=(_submission(witness="invented witness"),))
    unsupported = evidence.before_final_answer(content="answer")
    assert unsupported.allowed is False
    assert "exact fetched-text witness" in unsupported.feedback


def test_stale_or_contradicted_required_claim_cannot_pass() -> None:
    web, evidence = _active_controllers()
    web.on_tool_results(results=(_fetch(status="stale"),))
    evidence.on_tool_results(results=(_submission(),))
    stale = evidence.before_final_answer(content="answer")
    assert stale.allowed is False
    assert stale.reason == "required_claims_not_supported"

    web, evidence = _active_controllers()
    web.on_tool_results(results=(_fetch(),))
    evidence.on_tool_results(results=(_submission(judgment="contradicted"),))
    contradicted = evidence.before_final_answer(content="answer")
    assert contradicted.allowed is False
    assert contradicted.reason == "required_claims_not_supported"


def test_explicit_abstention_is_a_safe_terminal_answer() -> None:
    web, evidence = _active_controllers()
    evidence.on_tool_results(
        results=(
            ToolResult(
                tool_call_id="submit-abstain",
                name="evidence_submit",
                content=json.dumps(
                    {
                        "final_text": "I could not verify the release claim from fetched evidence.",
                        "claims": [],
                        "links": [],
                        "citations": [],
                        "abstain": True,
                        "abstention_reason": "No fetched source was available.",
                    }
                ),
            ),
        )
    )
    decision = evidence.before_final_answer(content="invented answer")
    assert decision.allowed is True
    assert decision.reason == "evidence_abstained"
    assert decision.replacement_content == "I could not verify the release claim from fetched evidence."


def test_loop_uses_verified_replacement_instead_of_unchecked_model_prose() -> None:
    web = WebResearchController()
    evidence = EvidenceRuntimeController(web)
    submission = json.loads(_submission().content)
    loop = KlaraLoop(
        llm=_ScriptedLlm(
            [
                ModelResponse(
                    content="",
                    tool_calls=(ToolCall(id="fetch-1", name="web_fetch", arguments={}),),
                ),
                ModelResponse(
                    content="",
                    tool_calls=(
                        ToolCall(id="submit-1", name="evidence_submit", arguments=submission),
                    ),
                ),
                ModelResponse(content="unchecked model prose"),
            ]
        ),
        tool_executor=ToolExecutor([_FixedFetchTool(), EvidenceSubmitTool()]),
        controllers=(web, evidence),
        policy=LoopPolicy(max_turns=3),
    )

    result = loop.run("What changed in the latest release?", run_id="replace-run")

    assert result.final_answer.startswith("Version 4 adds evidence control.")
    assert "unchecked model prose" not in result.final_answer
    assert result.messages[-1].content == result.final_answer
