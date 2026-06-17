import json
from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_trace_contains_decisions(tmp_path):
    trace_path = tmp_path / "runs.jsonl"
    AgenticRAGRuntime(trace_path=trace_path).run("Agentic RAG", save_trace=True)
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["schema_version"] == "v0.3"
    assert record["decisions"]
    assert any(decision["node_name"] == "plan_evidence_search" for decision in record["decisions"])
