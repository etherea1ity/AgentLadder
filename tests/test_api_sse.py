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
    """Constructor compatibility client; v0.3 runtime is deterministic and does not call it."""

    def chat(self, messages: list[Message]) -> LLMResponse:
        return LLMResponse(content="unused", model="test-llm")

    def stream_chat(self, messages: list[Message]) -> Iterator[LLMStreamChunk]:
        yield LLMStreamChunk(delta="unused", model="test-llm", done=True)


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LADDER_PAPER_ROOT", "data/papers")
    store = JsonlAppStore(tmp_path / "app")
    bus = SSEBus()
    service = RunService(store=store, bus=bus, llm_client=DeterministicStreamingLLMClient(), trace_path=str(tmp_path / "traces" / "runs.jsonl"))
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_bus] = lambda: bus
    app.dependency_overrides[get_run_service] = lambda: service
    return TestClient(app), store, service


def wait_for_terminal(client: TestClient, run_id: str):
    for _ in range(300):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["run"]["status"] in {"completed", "failed", "cancelled"}:
            return detail
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_api_run_lifecycle_events_trace_and_delete(tmp_path, monkeypatch):
    client, _store, service = make_client(tmp_path, monkeypatch)
    session = client.post("/api/sessions").json()
    created = client.post("/api/runs", json={"session_id": session["session_id"], "question": "tell me about react"}).json()
    run_id = created["run_id"]

    detail = wait_for_terminal(client, run_id)
    assert detail["run"]["status"] == "completed"
    assert detail["run"]["token_source"] == "estimated"
    assert detail["trace"] is not None
    assert detail["trace"]["schema_version"] == "v0.3"
    assert detail["trace"]["route"]["route"] == "rag"
    assert detail["trace"]["answer_frame"]["final_text"]
    assert detail["trace"]["answer_frame"]["sources"]
    assert "ReAct" in detail["trace"]["answer_frame"]["final_text"]
    event_types = [event["event_type"] for event in detail["events"]]
    assert "run_created" in event_types
    assert "answer_delta" in event_types
    assert "trace_saved" in event_types
    assert "run_completed" in event_types
    module_ids = [
        event["payload"].get("module_result", {}).get("module_id")
        for event in detail["events"]
        if event["event_type"].startswith("module_")
    ]
    assert "klara_v03_runtime" in module_ids

    stream_text = client.get(f"/api/runs/{run_id}/events/stream").text
    assert "event: run_created" in stream_text
    assert "event: run_completed" in stream_text

    deleted = client.delete(f"/api/sessions/{session['session_id']}").json()
    assert deleted["deleted"] is True
    assert client.get("/api/sessions").json()["sessions"] == []
    assert client.get(f"/api/sessions/{session['session_id']}").status_code == 404
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert created["run_id"] not in service._threads
    assert created["run_id"] not in service._cancel_requested


def test_api_uses_unified_runtime_when_provider_would_omit_usage(tmp_path, monkeypatch):
    client, _store, _service = make_client(tmp_path, monkeypatch)
    session = client.post("/api/sessions").json()
    created = client.post("/api/runs", json={"session_id": session["session_id"], "question": "解释 Self-RAG。"}).json()
    detail = wait_for_terminal(client, created["run_id"])
    assert detail["run"]["status"] == "completed"
    assert detail["run"]["token_source"] == "estimated"
    assert detail["trace"]["schema_version"] == "v0.3"
    assert detail["trace"]["answer_frame"]["final_text"]


def test_api_insufficient_info_and_cleans_runtime(tmp_path, monkeypatch):
    client, _store, service = make_client(tmp_path, monkeypatch)
    session = client.post("/api/sessions").json()
    created = client.post("/api/runs", json={"session_id": session["session_id"], "question": "qwerty_nonexistent_agent_ladder_topic"}).json()
    detail = wait_for_terminal(client, created["run_id"])
    assert detail["run"]["status"] == "completed"
    assert detail["trace"]["answer_frame"]["mode"] == "insufficient_info"
    assert detail["trace"]["answer_frame"]["sources"] == []
    assert created["run_id"] not in service._threads
    assert created["run_id"] not in service._cancel_requested
