from agent_ladder.knowledge.paper.corpus import PaperCorpus
from agent_ladder.knowledge.paper.visuals import VisualAssetStore


def test_visual_element_loader_has_figure_and_table():
    corpus = PaperCorpus()
    visuals = corpus.visuals()
    assert any(v.visual_type == "figure" for v in visuals)
    assert any(v.visual_type == "table" for v in visuals)
    assert VisualAssetStore().resolve(next(v for v in visuals if v.image_path))
