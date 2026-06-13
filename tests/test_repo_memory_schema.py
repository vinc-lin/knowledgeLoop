"""EntityMap dataclasses + JSON round-trip."""

from repo_memory.bridge.schema import (
    CONFIDENCE, EntityEntry, ModuleMap, EntityMap,
    to_dict, from_dict, save_entity_map, load_entity_map,
)


def _sample():
    entry = EntityEntry("IngestionPipeline", "src/ingest/pipeline.py",
                        "n1", [10, 88], "exact", 1.0)
    unm = EntityEntry("chunkDocument", "src/ingest/chunker.py",
                      None, None, "unmatched", 0.0)
    mod = ModuleMap("ingestion", None, "src/ingest", [entry], [unm])
    return EntityMap("headsha", "wikisha", "graphsha", [mod])


def test_confidence_constants():
    assert CONFIDENCE["exact"] == 1.0
    assert CONFIDENCE["unmatched"] == 0.0


def test_roundtrip_dict():
    em = _sample()
    rebuilt = from_dict(to_dict(em))
    assert rebuilt == em
    assert rebuilt.modules[0].entries[0].cbm_node_id == "n1"
    assert rebuilt.modules[0].unmatched[0].match_strategy == "unmatched"


def test_roundtrip_file(tmp_path):
    em = _sample()
    p = tmp_path / "entity_map.json"
    save_entity_map(em, str(p))
    assert load_entity_map(str(p)) == em
