"""The unified response envelope shape."""

from repo_memory.contract import envelope


def test_defaults():
    e = envelope({"x": 1})
    assert e["result"] == {"x": 1}
    assert e["freshness"] == "unverified"
    assert e["provenance"] == {"repo_head": None, "wiki_commit": None, "graph_commit": None}
    assert e["confidence"] is None
    assert e["warnings"] == []
    assert e["unmatched"] == []


def test_all_fields():
    e = envelope([], freshness="fresh",
                 provenance={"repo_head": "r", "wiki_commit": "w", "graph_commit": "g"},
                 confidence=0.9, warnings=["w1"], unmatched=[{"symbol": "S"}])
    assert e["freshness"] == "fresh"
    assert e["provenance"]["graph_commit"] == "g"
    assert e["confidence"] == 0.9
    assert e["warnings"] == ["w1"]
    assert e["unmatched"] == [{"symbol": "S"}]
