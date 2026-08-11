from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from klara.eval import export_jsonl, load_jsonl, project_public_events, validate_dataset
from klara.eval.trajectory import TrajectoryEvent, TrajectoryRecord, leakage_findings


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "algorithm" / "gate1_trajectories.jsonl"


def test_gold_trajectory_schema_and_all_id_links_pass() -> None:
    records = load_jsonl(FIXTURE)

    result = validate_dataset(records)

    assert result.total_records == 2
    assert result.schema_validation_rate == 1.0
    assert result.id_linkage_rate == 1.0
    assert result.leakage_findings == ()
    assert records[0].events[0].turn_id == "run_abstain:turn:0"
    assert records[0].to_dict()["events"][0]["turn_id"] == "run_abstain:turn:0"


def test_export_is_byte_deterministic_for_same_records(tmp_path: Path) -> None:
    records = load_jsonl(FIXTURE)

    first_hash = export_jsonl(records, tmp_path / "first.jsonl")
    second_hash = export_jsonl(tuple(reversed(records)), tmp_path / "second.jsonl")

    assert first_hash == second_hash
    assert (tmp_path / "first.jsonl").read_bytes() == (
        tmp_path / "second.jsonl"
    ).read_bytes()


def test_foreign_run_id_is_rejected() -> None:
    record = load_jsonl(FIXTURE)[0]
    changed = replace(record.events[0], run_id="run-foreign")

    with pytest.raises(ValueError, match="foreign run id"):
        replace(record, events=(changed, *record.events[1:]))


def test_tool_terminal_without_start_is_rejected() -> None:
    event = TrajectoryEvent(
        event_id="evt-1",
        run_id="run-1",
        seq=1,
        type="tool.completed",
        turn_index=1,
        state="completed",
        tool_call_id="tool-1",
    )

    with pytest.raises(ValueError, match="terminal without start"):
        TrajectoryRecord(run_id="run-1", events=(event,))


@pytest.mark.parametrize(
    "unsafe",
    [
        {"api_key": "do-not-store"},
        {"reasoning_content": "private provider trace"},
        {"message": "Authorization: Bearer abcdefghijklmnop"},
        {"message": "sk-abcdefghijklmnop"},
    ],
)
def test_secret_and_hidden_reasoning_scan_finds_unsafe_material(
    unsafe: dict[str, str],
) -> None:
    assert leakage_findings(unsafe)


def test_policy_decision_is_not_misclassified_as_hidden_reasoning() -> None:
    assert leakage_findings({"policy_decision": "abstain"}) == []


def test_public_event_projection_drops_prompts_results_and_reasoning() -> None:
    events = [
        {
            "event_id": "evt-1",
            "run_id": "run-1",
            "seq": 1,
            "type": "run.started",
            "payload": {"input": "private user prompt"},
        },
        {
            "event_id": "evt-2",
            "run_id": "run-1",
            "seq": 2,
            "type": "turn.started",
            "payload": {"turn_index": 1},
        },
        {
            "event_id": "evt-3",
            "run_id": "run-1",
            "seq": 3,
            "type": "tool.started",
            "payload": {
                "turn_index": 1,
                "tool_call": {
                    "id": "tool-1",
                    "name": "web_fetch",
                    "arguments": {"url": "https://private.test"},
                },
            },
        },
        {
            "event_id": "evt-4",
            "run_id": "run-1",
            "seq": 4,
            "type": "tool.completed",
            "payload": {
                "turn_index": 1,
                "tool_result": {
                    "tool_call_id": "tool-1",
                    "name": "web_fetch",
                    "content": "raw untrusted page",
                },
                "metrics": {"duration_ms": 4},
                "source_id": "src-1",
            },
        },
        {
            "event_id": "evt-5",
            "run_id": "run-1",
            "seq": 5,
            "type": "llm.completed",
            "payload": {
                "turn_index": 1,
                "reasoning": {"summary": "provider reasoning"},
            },
        },
        {
            "event_id": "evt-6",
            "run_id": "run-1",
            "seq": 6,
            "type": "run.completed",
            "payload": {"final_answer": "private answer"},
        },
    ]

    record = project_public_events(events, lineage_id="trace-v1")
    serialized = str(record.to_dict())

    assert record.source_ids == ("src-1",)
    assert "web_fetch" in serialized
    assert "duration_ms" in serialized
    assert "private user prompt" not in serialized
    assert "https://private.test" not in serialized
    assert "raw untrusted page" not in serialized
    assert "provider reasoning" not in serialized
    assert "private answer" not in serialized
