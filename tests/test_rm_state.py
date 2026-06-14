"""AppState holds loaded wiki/entity_map + cbm; load tolerates missing artifacts."""

import json
import os

from repo_memory.state import AppState, load_app_state


def test_load_missing_artifacts_degrades(tmp_path):
    st = load_app_state(wiki_dir=str(tmp_path / "nowiki"),
                        entity_map_path=str(tmp_path / "none.json"))
    assert isinstance(st, AppState)
    assert st.wiki is None and st.entity_map is None  # degraded, no exception


def test_load_present_artifacts(tmp_path):
    wd = tmp_path / "wiki"
    wd.mkdir()
    (wd / "module_tree.json").write_text(json.dumps({"m": {"path": "p", "components": [], "children": {}}}))
    (wd / "metadata.json").write_text(json.dumps({"generation_info": {"commit_id": "c"}, "files_generated": []}))
    em = tmp_path / "entity_map.json"
    em.write_text(json.dumps({"built_at_repo_head": "r", "wiki_commit": "c",
                              "graph_commit": None, "modules": []}))
    st = load_app_state(wiki_dir=str(wd), entity_map_path=str(em), repo_head="r")
    assert st.wiki is not None and st.wiki.wiki_commit == "c"
    assert st.entity_map is not None and st.entity_map.built_at_repo_head == "r"
    assert st.repo_head == "r"
