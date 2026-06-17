from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_agentic_rag_standard_run_has_answer_and_trace_state(tmp_path):
    result = AgenticRAGRuntime(trace_path=tmp_path / "runs.jsonl").run("Explain Agentic RAG evidence verification", save_trace=True)
    assert result.answer_frame.final_text
    assert result.state.route.route == "rag"
    assert result.trace_saved is True
    assert (tmp_path / "runs.jsonl").exists()
