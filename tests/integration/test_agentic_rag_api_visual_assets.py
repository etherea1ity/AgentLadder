from pathlib import Path
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


def test_main_chat_visual_assets_are_available_when_image_path_exists(monkeypatch):
    monkeypatch.setenv("AGENT_LADDER_PAPER_ROOT", "data/papers")
    client = TestClient(app)
    detail = _run_chat(client, "Explain figure aware RAG in Chinese, include figure")
    assert detail["run"]["status"] == "completed", detail
    visuals = detail["trace"]["answer_frame"]["visual_sources"]
    assert visuals
    visual = visuals[0]
    assert visual["caption"]
    image_path = visual.get("image_path")
    if image_path and Path(image_path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
        response = client.get(f"/api/assets/local?path={image_path}")
        assert response.status_code == 200
        assert response.content


def test_visual_text_placeholder_is_not_image_route():
    client = TestClient(app)
    path = "data/papers/fixtures/paper_visual_transformer/figures/figure1.txt"
    assert Path(path).exists()
    response = client.get(f"/api/assets/local?path={path}")
    assert response.status_code == 200
    assert response.text
