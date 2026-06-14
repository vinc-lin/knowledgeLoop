"""Central freshness enum (graph>wiki precedence) + require_fresh gate."""

from repo_memory.state import AppState
from repo_memory.bridge.schema import EntityMap
from repo_memory.wiki.loader import WikiData
from repo_memory.grounding import compute_freshness, require_fresh


def _state(*, cbm=True, repo_head="r", graph_commit="r", wiki_commit=None, em=True):
    entity_map = EntityMap(repo_head, wiki_commit, graph_commit, []) if em else None
    wiki = WikiData({}, {}, {}, wiki_commit, []) if wiki_commit is not None else None
    return AppState(wiki_dir="w", entity_map_path="e", repo_head=repo_head,
                    cbm=(object() if cbm else None), wiki=wiki, entity_map=entity_map)


def test_unverified_when_no_cbm_or_missing_commit():
    assert compute_freshness(_state(cbm=False)) == "unverified"
    assert compute_freshness(_state(graph_commit=None)) == "unverified"
    assert compute_freshness(_state(em=False)) == "unverified"


def test_stale_graph_beats_wiki():
    assert compute_freshness(_state(graph_commit="OLD", wiki_commit="OLD")) == "stale-graph"


def test_entries_stale_forces_stale_graph():
    assert compute_freshness(_state(graph_commit="r"), entries_stale=True) == "stale-graph"


def test_stale_wiki_when_only_wiki_behind():
    assert compute_freshness(_state(graph_commit="r", wiki_commit="OLD")) == "stale-wiki"


def test_fresh_when_all_aligned():
    assert compute_freshness(_state(graph_commit="r", wiki_commit="r")) == "fresh"


def test_require_fresh_none_when_current():
    assert require_fresh(_state(graph_commit="r")) is None


def test_require_fresh_returns_blocking_freshness():
    assert require_fresh(_state(cbm=False)) == "unverified"
    assert require_fresh(_state(graph_commit="OLD")) == "stale-graph"


def test_require_fresh_does_not_block_on_stale_wiki():
    assert require_fresh(_state(graph_commit="r", wiki_commit="OLD")) is None
