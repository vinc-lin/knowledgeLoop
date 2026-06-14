"""get_related_files reads the precomputed entity_map and verifies on access."""

import pytest

from repo_memory.state import AppState
from repo_memory.bridge.schema import EntityMap, ModuleMap, EntityEntry, NodeRecord
from repo_memory.tools import bridge_tools


class FakeProbe:
    def __init__(self, present):
        self._present = present  # dict qn -> NodeRecord

    async def prefetch(self, qns):
        return None

    def lookup(self, node_id):
        return self._present.get(node_id)


def _state(entity_map):
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", entity_map=entity_map)


def _em():
    entry = EntityEntry("Cfg", "p/m.py", "p.m.Cfg", [1, 5], "exact", 1.0)
    return EntityMap("r", "w", "g", [ModuleMap("mod", None, "p", [entry], [])])


@pytest.mark.asyncio
async def test_returns_entries_and_confidence_when_fresh():
    probe = FakeProbe({"p.m.Cfg": NodeRecord("p.m.Cfg", "Cfg", "p.m.Cfg", "p/m.py", 1, 5)})
    e = await bridge_tools.get_related_files(_state(_em()), "mod", probe=probe)
    assert e["result"]["module"] == "mod"
    assert e["result"]["files"] == ["p/m.py"]
    assert e["confidence"] == 1.0
    assert e["result"]["entries"][0]["stale"] is False


@pytest.mark.asyncio
async def test_marks_stale_when_node_gone():
    probe = FakeProbe({})  # node missing now
    e = await bridge_tools.get_related_files(_state(_em()), "mod", probe=probe)
    assert e["result"]["entries"][0]["stale"] is True


@pytest.mark.asyncio
async def test_degrades_without_entity_map():
    e = await bridge_tools.get_related_files(_state(None), "mod", probe=FakeProbe({}))
    assert e["result"] is None and e["warnings"]


@pytest.mark.asyncio
async def test_degrades_when_cbm_down_serves_unverified():
    # No probe passed AND state.cbm is None -> serve unverified, no graph call
    st = AppState(wiki_dir="w", entity_map_path="e", repo_head="r", entity_map=_em())
    e = await bridge_tools.get_related_files(st, "mod")
    assert e["freshness"] == "unverified"
    assert any("CBM" in w for w in e["warnings"])
    assert e["result"]["files"] == ["p/m.py"]
    assert e["confidence"] == 1.0


@pytest.mark.asyncio
async def test_module_not_in_entity_map():
    e = await bridge_tools.get_related_files(_state(_em()), "nope", probe=FakeProbe({}))
    assert e["result"] is None
    assert any("not in entity_map" in w for w in e["warnings"])
