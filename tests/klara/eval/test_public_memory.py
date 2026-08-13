from __future__ import annotations

import json

import pytest

from klara.eval.public_memory import (
    LONGMEMEVAL_DATA_SHA256,
    load_locomo,
    run_longmemeval_oracle_contract,
    select_locomo_questions,
)


def _conversation(index: int) -> dict[str, object]:
    return {
        "conversation": {
            "speaker_a": "A",
            "speaker_b": "B",
            "session_1_date_time": "1:00 pm on 1 January, 2026",
            "session_1": [
                {"speaker": "A", "dia_id": f"D{index}:1", "text": f"fact {index}"},
                {"speaker": "B", "dia_id": f"D{index}:2", "text": f"reply {index}"},
            ],
        },
        "qa": [
            {
                "question": f"What fact {index}?",
                "answer": f"fact {index}",
                "evidence": [f"D{index}:1"],
                "category": 1,
            }
        ],
    }


def test_locomo_adapter_preserves_public_labels(tmp_path) -> None:
    path = tmp_path / "locomo10.json"
    payload = [_conversation(index) for index in range(1, 11)]
    path.write_text(json.dumps(payload), encoding="utf-8")

    turns, questions, stats = load_locomo(path)

    assert len(turns) == 20
    assert len(questions) == 10
    assert questions[0].answer == "fact 1"
    assert questions[0].evidence_ids == ("D1:1",)
    assert stats["conversations"] == 10
    assert select_locomo_questions(questions, per_conversation=1) == questions


def test_locomo_adapter_rejects_wrong_conversation_count(tmp_path) -> None:
    path = tmp_path / "locomo10.json"
    path.write_text(json.dumps([_conversation(1)]), encoding="utf-8")

    with pytest.raises(ValueError, match="ten_conversations"):
        load_locomo(path)


def test_longmemeval_contract_returns_a_report(tmp_path, monkeypatch) -> None:
    path = tmp_path / "oracle.json"
    payload = [
        {
            "question_id": f"q-{index}",
            "question_type": f"type-{index % 5}",
            "question": "question",
            "answer": "answer",
            "haystack_sessions": [[{"role": "user", "content": "evidence"}]],
            "haystack_session_ids": [f"session-{index}"],
            "answer_session_ids": [f"session-{index}"],
            "haystack_dates": ["2026-01-01"],
        }
        for index in range(500)
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "klara.eval.public_memory.LONGMEMEVAL_DATA_SHA256",
        __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    )

    report = run_longmemeval_oracle_contract(path, sample_size=60)

    assert report["passed"]
    assert report["benchmark"] == "LongMemEval"
    assert report["selection"]["sample_size"] == 60
