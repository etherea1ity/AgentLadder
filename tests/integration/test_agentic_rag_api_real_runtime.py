import time

from fastapi.testclient import TestClient

from apps.api.main import app


def test_main_chat_api_does_not_return_mock_answer(monkeypatch):
    monkeypatch.setenv("AGENT_LADDER_PAPER_ROOT", "data/papers")
    client = TestClient(app)
    session = client.post("/api/sessions").json()
    created = client.post("/api/runs", json={"session_id": session["session_id"], "question": "qwerty_nonexistent_agent_ladder_topic"}).json()
    for _ in range(240):
        detail = client.get(f"/api/runs/{created['run_id']}").json()
        if detail["run"]["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("run did not finish")
    frame = detail["trace"]["answer_frame"]
    assert frame["mode"] == "insufficient_info"
    assert frame["sources"] == []
    assert "mock" not in frame["final_text"].lower()
