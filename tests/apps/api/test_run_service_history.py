from __future__ import annotations

from apps.api.schemas import MessageRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.app.user_context import UserContext
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
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=FinalLlm(),
        user_context=UserContext.local_default(),
    )

    previous_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="draw Klara",
        status="completed",
        created_at="2026-06-18T12:34:56+00:00",
    )
    previous_assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content="I can make that image.",
        status="completed",
        created_at="2026-06-18T12:35:56+00:00",
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="generate it",
        status="completed",
        created_at="2026-06-18T12:36:56+00:00",
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
        ("user", "[Thu 2026-06-18 12:34 UTC] draw Klara"),
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
        content="search the latest World Cup news",
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


def test_current_user_message_is_timestamped_for_model_boundary(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=FinalLlm(),
        user_context=UserContext(
            user_id="local-user",
            display_name="Local User",
            timezone="Asia/Shanghai",
            storage_key="local-user",
        ),
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="World Cup status?",
        status="completed",
        created_at="2026-06-18T12:34:56+00:00",
    )

    assert (
        service._model_visible_content(current_user)
        == "[Thu 2026-06-18 20:34 GMT+08] World Cup status?"
    )
    assert current_user.content == "World Cup status?"
