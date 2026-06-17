from agent_ladder.knowledge.paper.validation import validate_paper_corpus


def test_fixture_and_real_corpus_validate():
    assert validate_paper_corpus("data/papers").ok
