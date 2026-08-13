from pathlib import Path

from klara.eval.permission_engine import evaluate_permission_engine


ROOT = Path(__file__).parents[3]


def test_permission_engine_gate_passes_every_security_check() -> None:
    report = evaluate_permission_engine(ROOT)
    assert report["passed"]
    assert report["metrics"]["critical_isolation_and_bypass_rate"] == 1.0
    assert report["metrics"]["raw_argument_leak_count"] == 0
    assert report["behavior"]["question_answer_consistent"] is True
    assert report["behavior"]["strange_response_p0_count"] == 0
