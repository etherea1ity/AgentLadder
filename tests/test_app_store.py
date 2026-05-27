from apps.api.schemas import MessageRecord
from apps.api.services.app_store import JsonlAppStore


def test_jsonl_store_replays_sessions_messages_and_hard_delete(tmp_path):
    store = JsonlAppStore(tmp_path)
    session = store.create_session()
    message = MessageRecord(session_id=session.session_id, role="user", content="Hello", status="completed")
    store.save_message(message)

    assert store.list_sessions()[0].session_id == session.session_id
    assert store.list_messages(session.session_id)[0].content == "Hello"

    deleted = store.delete_session(session.session_id, tmp_path / "traces" / "runs.jsonl")
    assert deleted and deleted.deleted_at
    assert store.list_sessions() == []
    assert store.get_visible_session(session.session_id) is None
    assert store.list_messages(session.session_id) == []
