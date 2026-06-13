"""Deterministic Wiki<->Graph join."""

from repo_memory.bridge.schema import NodeRecord
from repo_memory.bridge.builder import build_entity_map


def _tree():
    return {
        "ingestion": {
            "path": "src/ingest",
            "components": [
                "src/ingest/pipeline.py::IngestionPipeline",
                "src/ingest/ghost.py::GhostClass",
            ],
            "children": {},
        }
    }


def test_exact_match_and_unmatched():
    nodes = [NodeRecord("n1", "IngestionPipeline", "src.ingest.IngestionPipeline",
                        "src/ingest/pipeline.py", 10, 88)]
    em = build_entity_map(_tree(), nodes, repo_head="HEAD")
    mod = em.modules[0]
    assert mod.module == "ingestion"
    assert em.built_at_repo_head == "HEAD"
    # IngestionPipeline resolves exactly
    assert len(mod.entries) == 1
    assert mod.entries[0].cbm_node_id == "n1"
    assert mod.entries[0].match_strategy == "exact"
    assert mod.entries[0].confidence == 1.0
    assert mod.entries[0].lines == [10, 88]
    # GhostClass is nowhere in the graph -> unmatched
    assert len(mod.unmatched) == 1
    assert mod.unmatched[0].symbol == "GhostClass"
    assert mod.unmatched[0].match_strategy == "unmatched"
    assert mod.unmatched[0].cbm_node_id is None


def test_walks_children():
    tree = {
        "parent": {"path": "src", "components": [], "children": {
            "child": {"path": "src/child", "components": [], "children": {}}
        }}
    }
    em = build_entity_map(tree, [])
    names = {m.module for m in em.modules}
    assert names == {"parent", "child"}


def test_qualified_suffix_when_roots_differ():
    # CBM stored an absolute path; Wiki path is repo-relative -> suffix match
    nodes = [NodeRecord("n2", "Chunker", "ingest.Chunker",
                        "/abs/repo/src/ingest/chunker.py", 1, 9)]
    tree = {"m": {"path": "src/ingest",
                  "components": ["src/ingest/chunker.py::Chunker"], "children": {}}}
    em = build_entity_map(tree, nodes)
    e = em.modules[0].entries[0]
    assert e.match_strategy == "qualified_suffix"
    assert e.confidence == 0.85
    assert e.cbm_node_id == "n2"


def test_file_only_when_symbol_missing_but_file_present():
    nodes = [NodeRecord("n3", "SomethingElse", "x.SomethingElse",
                        "src/ingest/pipeline.py", 1, 5)]
    tree = {"m": {"path": "src/ingest",
                  "components": ["src/ingest/pipeline.py::IngestionPipeline"],
                  "children": {}}}
    em = build_entity_map(tree, nodes)
    e = em.modules[0].entries[0]
    assert e.match_strategy == "file_only"
    assert e.confidence == 0.5
    assert e.cbm_node_id is None
