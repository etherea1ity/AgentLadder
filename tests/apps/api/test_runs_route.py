from __future__ import annotations

import json

from apps.api.routes.runs import get_run
from apps.api.schemas import MessageRecord, RunRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.core.messages import ModelResponse


class FinalLlm:
    def complete(self, **_: object) -> ModelResponse:
        return ModelResponse(content="ok")


def test_run_detail_returns_only_a_public_trace_reference(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    user = MessageRecord(session_id=session.session_id, role="user", content="hello")
    assistant = MessageRecord(session_id=session.session_id, role="assistant", content="ok")
    run = RunRecord(
        run_id="run-public-trace",
        session_id=session.session_id,
        user_message_id=user.message_id,
        assistant_message_id=assistant.message_id,
        status="completed",
    )
    for message in (user, assistant):
        store.save_message(message)
    store.save_run(run)
    trace_path = tmp_path / "traces.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "run_id": run.run_id,
                "type": "run.completed",
                "payload": {"raw_private_value": "must-not-cross-api"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=FinalLlm(),
        trace_path=str(trace_path),
    )

    detail = get_run(run.run_id, store=store, run_service=service)

    assert detail.trace == {
        "schema_version": "klara.trace-reference.v1",
        "run_id": run.run_id,
        "available": True,
        "latest_event_type": "run.completed",
        "private_payload_exposed": False,
    }
    assert "must-not-cross-api" not in json.dumps(detail.model_dump(mode="json"))
