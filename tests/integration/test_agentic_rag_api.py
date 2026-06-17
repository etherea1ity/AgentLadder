import time

from fastapi.testclient import TestClient

from apps.api.main import app


def _run_chat(client: TestClient, question: str):
    session = client.post("/api/sessions").json()
    created = client.post("/api/runs", json={"session_id": session["session_id"], "question": question}).json()
    for _ in range(240):
        detail = client.get(f"/api/runs/{created['run_id']}").json()
        if detail["run"]["status"] in {"completed", "failed", "cancelled"}:
            return detail
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_main_chat_api_returns_real_unified_runtime_answer(monkeypatch):
    monkeypatch.setenv("AGENT_LADDER_PAPER_ROOT", "data/papers")
    client = TestClient(app)
    detail = _run_chat(client, "Explain Self-RAG in Chinese.")
    assert detail["run"]["status"] == "completed", detail
    trace = detail["trace"]
    assert trace["schema_version"] == "v0.3"
    frame = trace["answer_frame"]
    assert frame["final_text"]
    assert "Klara" in frame["final_text"]
    assert trace["route"]["route"] == "rag"
    assert trace["run_mode"] == "agentic_rag"
    assert frame["sources"]
    assert len(trace["search_plan"]["search_units"]) >= 5
    assert len(trace["retrieval_attempts"]) > 0
    assert trace["verification"]["status"] in {"passed", "revised"}
    assert "/mnt/c/" not in str(detail)
    assert "C:\\\\" not in str(detail)


def test_standalone_agentic_endpoint_is_not_registered():
    client = TestClient(app)
    response = client.post("/api/agentic-rag/ask", json={"question": "Agentic RAG", "paper_root": "data/papers"})
    assert response.status_code == 404
