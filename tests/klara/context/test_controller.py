from __future__ import annotations

from klara.app.user_context import UserContext
from klara.context.controller import ContextController
from klara.context.policy import ContextPolicy
from klara.core.messages import KlaraMessage


def test_controller_emits_public_metrics_but_keeps_summary_private(tmp_path) -> None:
    controller = ContextController(
        policy=ContextPolicy(
            max_input_tokens=800,
            reserved_system_tokens=100,
            reserved_output_tokens=100,
            recent_messages=4,
            minimum_recent_messages=2,
            summary_max_chars=600,
            tool_result_max_chars=160,
        ),
        user_context=UserContext.local_default(),
        capabilities=("todo_write",),
        workspace_root=tmp_path,
    )
    controller.on_run_start(user_input="continue", run_id="run-1")
    controller.drain_events()
    messages = [
        KlaraMessage(role="user" if index % 2 == 0 else "assistant", content=f"SECRET-{index} " + "x" * 500)
        for index in range(10)
    ]

    prepared = controller.prepare_next_turn(messages)
    events = controller.drain_events()
    compacted = next(event for event in events if event.type == "context.compacted")

    assert len(prepared) < len(messages)
    assert "SECRET-0" in controller.system_prompt_suffix()
    assert "SECRET-0" not in str(compacted.payload)
    assert compacted.payload["summary_content_exposed"] is False
    assert compacted.payload["summary_sha256"]
