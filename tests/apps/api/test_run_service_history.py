from __future__ import annotations

from apps.api.schemas import MessageRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.context.history import GENERATED_IMAGE_PLACEHOLDER
from klara.core.messages import ModelResponse


class FinalLlm:
    """Tiny LLM fixture; this test only needs RunService construction."""

    def complete(self, **_: object) -> ModelResponse:
        """Return a final answer if the fixture is accidentally invoked."""

        return ModelResponse(content="ok")


def test_conversation_history_uses_completed_messages_before_current_turn(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(store=store, bus=SSEBus(), llm_client=FinalLlm())

    previous_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="draw Klara",
        status="completed",
    )
    previous_assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content="I can make that image.",
        status="completed",
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="generate it",
        status="completed",
    )
    pending_assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content="",
        status="running",
    )
    for message in (previous_user, previous_assistant, current_user, pending_assistant):
        store.save_message(message)

    history = service._conversation_history(
        session.session_id,
        before_message_id=current_user.message_id,
    )

    assert [(message.role, message.content) for message in history] == [
        ("user", "draw Klara"),
        ("assistant", "I can make that image."),
    ]


def test_conversation_history_removes_local_generated_image_urls(tmp_path) -> None:
    """Prior local image assets should not pollute later unrelated tool choices."""

    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(store=store, bus=SSEBus(), llm_client=FinalLlm())

    previous_assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content=(
            "[Open generated image]"
            "(/api/assets/local?path=data/assets/images/20260617/generated.png)"
        ),
        status="completed",
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="搜索世界杯最新消息",
        status="completed",
    )
    for message in (previous_assistant, current_user):
        store.save_message(message)

    history = service._conversation_history(
        session.session_id,
        before_message_id=current_user.message_id,
    )

    assert len(history) == 1
    assert history[0].content == GENERATED_IMAGE_PLACEHOLDER
