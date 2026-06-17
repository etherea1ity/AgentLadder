from agent_ladder.rag.agentic.normalizer import parse_answer_requirements, infer_output_style


def test_answer_requirement_requested_count_and_diversity():
    req = parse_answer_requirements("给我 10 篇 Agentic RAG 相关论文，并按路线分类")
    assert req.requested_count == 10
    assert req.need_diversity is True
    assert infer_output_style("give me 10 papers").answer_style == "paper_list"
