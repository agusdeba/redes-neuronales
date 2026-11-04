from src.common.config import source_cfg, sources


def test_only_wikidata_skips_robots():
    names = [n for n in sources()["sources"] if source_cfg(n).get("respect_robots", True) is False]
    assert names == ["wikidata"]
    assert "github.com/agusdeba/redes-neuronales" in source_cfg("wikidata")["user_agent"]
