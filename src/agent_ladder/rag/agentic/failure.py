from __future__ import annotations

from agent_ladder.rag.contracts.agentic import FailurePolicy


class FailurePolicyHandler:
    def __init__(self, policy: FailurePolicy | None = None) -> None:
        self.policy = policy or FailurePolicy()

    def allow_json_repair(self) -> bool:
        return self._consume("json_repair_used", self.policy.max_json_repair)

    def allow_query_rewrite(self) -> bool:
        return self._consume("query_rewrite_used", self.policy.max_query_rewrite)

    def allow_search_expansion(self) -> bool:
        return self._consume("search_expansion_used", self.policy.max_search_expansion)

    def allow_answer_revision(self) -> bool:
        return self._consume("answer_revision_used", self.policy.max_answer_revision)

    def _consume(self, attr: str, limit: int) -> bool:
        used = getattr(self.policy, attr)
        if used >= limit:
            return False
        setattr(self.policy, attr, used + 1)
        return True
