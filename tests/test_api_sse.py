from __future__ import annotations

import time
from collections.abc import Iterator

from fastapi.testclient import TestClient

from agent_ladder.llm.base import BaseLLMClient, LLMResponse, LLMStreamChunk, Message
from apps.api.dependencies import get_bus, get_run_service, get_store
from apps.api.main import app
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus


class DeterministicStreamingLLMClient(BaseLLMClient):
    """Test-local provider; production code uses the real DashScope client."""

    def chat(self, messages: list[Message]) -> LLMResponse:
        return LLMResponse(content=self._answer(messages), model="test-llm")

    def stream_chat(self, messages: list[Message]) -> Iterator[LLMStreamChunk]:
        answer = self._answer(messages)
        for part in answer.split(" "):
            yield LLMStreamChunk(delta=part + " ", model="test-llm")
        yield LLMStreamChunk(model="test-llm", prompt_tokens=12, completion_tokens=len(answer.split()), done=True)

    def _answer(self, messages: list[Message]) -> str:
        question = messages[-1]["content"] if messages else ""
        if "agent" in question.lower():
            return "An AI Agent is a system that receives a question, calls a model, produces an answer, and records the run as a trace."
        return f"Agent Ladder received your question: {question}"


def make_client(tmp_path):
    store = JsonlAppStore(tmp_path / "app")
    bus = SSEBus()
    service = RunService(store=store, bus=bus, llm_client=DeterministicStreamingLLMClient(), trace_path=str(tmp_path / "traces" / "runs.jsonl"))
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_bus] = lambda: bus
    app.dependency_overrides[get_run_service] = lambda: service
    return TestClient(app), store


def wait_for_terminal(client: TestClient, run_id: str):
    for _ in range(100):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["run"]["status"] in {"completed", "failed", "cancelled"}:
            return detail
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_api_run_lifecycle_events_trace_and_delete(tmp_path):
    client, _store = make_client(tmp_path)
    session = client.post("/api/sessions").json()
    created = client.post("/api/runs", json={"session_id": session["session_id"], "question": "What is an AI Agent?"}).json()
    run_id = created["run_id"]

    detail = wait_for_terminal(client, run_id)
    assert detail["run"]["status"] == "completed"
    assert detail["run"]["prompt_tokens"] == 12
    assert detail["run"]["completion_tokens"] > 0
    assert detail["run"]["total_tokens"] == detail["run"]["prompt_tokens"] + detail["run"]["completion_tokens"]
    assert detail["run"]["token_source"] == "reported"
    assert detail["trace"] is not None
    assert detail["trace"]["schema_version"] == "v0.1"
    assert [message["role"] for message in detail["trace"]["prompt"]["messages"]] == ["system", "user"]
    assert detail["trace"]["usage"]["input_tokens"] == detail["run"]["prompt_tokens"]
    assert detail["trace"]["usage"]["output_tokens"] == detail["run"]["completion_tokens"]
    assert detail["trace"]["usage"]["total_tokens"] == detail["run"]["total_tokens"]
    assert detail["trace"]["usage"]["source"] == "reported"
    event_types = [event["event_type"] for event in detail["events"]]
    assert "run_created" in event_types
    assert "answer_delta" in event_types
    assert "run_completed" in event_types

    stream_text = client.get(f"/api/runs/{run_id}/events/stream").text
    assert "event: run_created" in stream_text
    assert "event: run_completed" in stream_text

    deleted = client.delete(f"/api/sessions/{session['session_id']}").json()
    assert deleted["deleted"] is True
    assert client.get("/api/sessions").json()["sessions"] == []
    assert client.get(f"/api/sessions/{session['session_id']}").status_code == 404
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get(f"/api/runs/{run_id}/events").status_code == 404
    assert not (tmp_path / "app" / "messages.jsonl").read_text(encoding="utf-8").strip()
    assert not (tmp_path / "app" / "runs.jsonl").read_text(encoding="utf-8").strip()
    assert not (tmp_path / "app" / "run_events.jsonl").read_text(encoding="utf-8").strip()
    assert not (tmp_path / "traces" / "runs.jsonl").read_text(encoding="utf-8").strip()


class NoUsageStreamingLLMClient(DeterministicStreamingLLMClient):
    def stream_chat(self, messages: list[Message]) -> Iterator[LLMStreamChunk]:
        answer = self._answer(messages)
        yield LLMStreamChunk(delta=answer, model="no-usage-llm")
        yield LLMStreamChunk(model="no-usage-llm", done=True)


def test_api_estimates_tokens_when_provider_omits_usage(tmp_path):
    store = JsonlAppStore(tmp_path / "app")
    bus = SSEBus()
    service = RunService(store=store, bus=bus, llm_client=NoUsageStreamingLLMClient(), trace_path=str(tmp_path / "traces" / "runs.jsonl"))
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_bus] = lambda: bus
    app.dependency_overrides[get_run_service] = lambda: service
    client = TestClient(app)

    session = client.post("/api/sessions").json()
    created = client.post("/api/runs", json={"session_id": session["session_id"], "question": "解释傅里叶变换公式"}).json()
    detail = wait_for_terminal(client, created["run_id"])

    assert detail["run"]["token_source"] == "estimated"
    assert detail["run"]["prompt_tokens"] > 0
    assert detail["run"]["completion_tokens"] > 0
    assert detail["run"]["total_tokens"] == detail["run"]["prompt_tokens"] + detail["run"]["completion_tokens"]
    assert detail["trace"]["usage"]["source"] == "estimated"
