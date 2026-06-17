import os
from agent_ladder.knowledge.paper.corpus import PaperCorpus
from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_default_uses_fixtures_and_real_root_uses_processed():
    assert len(PaperCorpus().list_papers()) >= 3
    assert len(PaperCorpus("data/papers").list_papers()) >= 10


def test_env_var_can_be_used_by_cli_path(monkeypatch):
    monkeypatch.setenv("AGENT_LADDER_PAPER_ROOT", "data/papers")
    root = os.environ["AGENT_LADDER_PAPER_ROOT"]
    result = AgenticRAGRuntime(paper_root=root).run("Agentic RAG", save_trace=False)
    assert result.state.evidence_pack.items
    assert "C:\\" not in root
