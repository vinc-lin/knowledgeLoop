"""graph_is_current: the fail-closed freshness gate for assess_impact."""

from repo_memory.state import AppState
from repo_memory.bridge.schema import EntityMap
from repo_memory.grounding import graph_is_current


def _state(cbm, repo_head, graph_commit, *, entity_map=True):
    em = EntityMap(repo_head, None, graph_commit, []) if entity_map else None
    return AppState(wiki_dir="w", entity_map_path="e", repo_head=repo_head, cbm=cbm, entity_map=em)


def test_current_when_cbm_and_commits_match():
    assert graph_is_current(_state(object(), "r1", "r1")) is True


def test_not_current_when_cbm_none():
    assert graph_is_current(_state(None, "r1", "r1")) is False


def test_not_current_when_graph_stale():
    assert graph_is_current(_state(object(), "r1", "rOLD")) is False


def test_not_current_when_no_entity_map():
    assert graph_is_current(_state(object(), "r1", "r1", entity_map=False)) is False


def test_not_current_when_graph_commit_none():
    assert graph_is_current(_state(object(), "r1", None)) is False
