"""Wiki tools return envelopes and degrade when wiki is missing."""

from repo_memory.state import AppState
from repo_memory.wiki.loader import WikiData
from repo_memory.tools import wiki_tools


def _state_with_wiki():
    wiki = WikiData(
        module_tree={"a": {"path": "pa", "components": [], "children": {
            "b": {"path": "pa/b", "components": [], "children": {}}}}},
        metadata={"generation_info": {"commit_id": "c"}},
        docs={"overview.md": "# Repo\n", "a.md": "# a module\n"},
        wiki_commit="c", files_generated=["overview.md", "a.md"],
    )
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", wiki=wiki)


def test_overview_and_provenance():
    e = wiki_tools.get_repo_overview(_state_with_wiki())
    assert "Repo" in e["result"]["overview"]
    assert e["provenance"]["wiki_commit"] == "c"
    assert e["provenance"]["repo_head"] == "r"


def test_list_modules_walks_children():
    e = wiki_tools.list_modules(_state_with_wiki())
    assert set(e["result"]) == {"a", "b"}


def test_search_wiki():
    e = wiki_tools.search_wiki(_state_with_wiki(), "module")
    assert e["result"] and e["result"][0]["doc"] == "a.md"


def test_get_module_doc_found_and_missing():
    st = _state_with_wiki()
    e = wiki_tools.get_module_doc(st, "a")
    assert e["result"]["module"] == "a" and e["result"]["path"] == "pa"
    miss = wiki_tools.get_module_doc(st, "zzz")
    assert miss["result"] is None and miss["warnings"]


def test_degrades_without_wiki():
    st = AppState(wiki_dir="w", entity_map_path="e")
    e = wiki_tools.get_repo_overview(st)
    assert e["result"] is None and e["warnings"]


def test_wiki_tools_report_freshness():
    from repo_memory.bridge.schema import EntityMap
    st = _state_with_wiki()
    st.cbm = object()
    st.wiki.wiki_commit = "r"
    st.entity_map = EntityMap("r", "r", "r", [])
    assert wiki_tools.get_repo_overview(st)["freshness"] == "fresh"
    assert wiki_tools.list_modules(st)["freshness"] == "fresh"
    assert wiki_tools.search_wiki(st, "x")["freshness"] == "fresh"
