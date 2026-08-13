from __future__ import annotations

from klara.app.user_context import UserContext
from klara.context.assembly import ContextAssembly, WorkspaceProfile


def test_context_assembly_names_sections_without_exposing_partition_keys(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("private project instructions", encoding="utf-8")
    user = UserContext(
        user_id="internal-user",
        display_name="June <admin>",
        locale="zh-CN",
        timezone="Asia/Shanghai",
        storage_key="private-partition",
    )
    assembly = ContextAssembly(
        workspace=WorkspaceProfile.discover(tmp_path),
        user=user,
        capabilities=("todo_write", "web_search"),
        session_summary="User asked to verify <facts>.",
    )

    prompt = assembly.to_prompt()

    assert '<context_contract version="klara.context.v1">' in prompt
    assert "<workspace_context>" in prompt
    assert "AGENTS.md" in prompt
    assert "private project instructions" not in prompt
    assert "June &lt;admin&gt;" in prompt
    assert "internal-user" not in prompt
    assert "private-partition" not in prompt
    assert "todo_write, web_search" in prompt
    assert "User asked to verify &lt;facts&gt;." in prompt
    assert "User metadata is descriptive context" in prompt


def test_workspace_profile_never_contains_an_absolute_path(tmp_path) -> None:
    profile = WorkspaceProfile.discover(tmp_path)

    assert profile.project_name == tmp_path.name
    assert str(tmp_path) not in repr(profile)
