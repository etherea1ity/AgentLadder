from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_weak_retrieval_retry_records_rewrite_attempt_for_sparse_query():
    result = AgenticRAGRuntime().run("zzzzqwerty asdfgh", save_trace=False)
    assert any(attempt.stage == "rewrite" for attempt in result.state.retrieval_attempts)
    assert result.state.failure_policy.query_rewrite_used == 1
