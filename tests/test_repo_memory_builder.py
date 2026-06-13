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
