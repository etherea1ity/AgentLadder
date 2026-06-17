from agent_ladder.rag.agentic.failure import FailurePolicyHandler


def test_failure_policy_allows_each_recovery_once():
    handler = FailurePolicyHandler()
    assert handler.allow_query_rewrite() is True
    assert handler.allow_query_rewrite() is False
    assert handler.allow_search_expansion() is True
    assert handler.allow_answer_revision() is True
    assert handler.allow_answer_revision() is False
