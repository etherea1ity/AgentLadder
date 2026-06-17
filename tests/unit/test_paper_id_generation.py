from agent_ladder.knowledge.paper.ids import is_valid_paper_id, stable_paper_id


def test_stable_paper_id_is_repeatable_and_safe():
    pid = stable_paper_id("Self-RAG: Learning to Retrieve, Generate, and Critique", 2023)
    assert pid == stable_paper_id("Self-RAG: Learning to Retrieve, Generate, and Critique", 2023)
    assert is_valid_paper_id(pid)
