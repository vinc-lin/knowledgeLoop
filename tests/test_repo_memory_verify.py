"""verify-on-access marks entries stale when the graph no longer agrees."""

from repo_memory.bridge.schema import NodeRecord, EntityEntry
from repo_memory.bridge.verify import verify_entries


class FakeProbe:
    def __init__(self, nodes):
        self._by_id = {n.node_id: n for n in nodes}

    def lookup(self, node_id):
        return self._by_id.get(node_id)


def _entry(node_id, lines):
    return EntityEntry("Sym", "src/a.py", node_id, lines, "exact", 1.0)


def test_present_node_not_stale():
    probe = FakeProbe([NodeRecord("n1", "Sym", "a.Sym", "src/a.py", 10, 20)])
    out = verify_entries([_entry("n1", [10, 20])], probe)
    assert out[0].stale is False


def test_missing_node_is_stale():
    probe = FakeProbe([])
    out = verify_entries([_entry("n1", [10, 20])], probe)
    assert out[0].stale is True


def test_moved_lines_is_stale():
    probe = FakeProbe([NodeRecord("n1", "Sym", "a.Sym", "src/a.py", 30, 40)])
    out = verify_entries([_entry("n1", [10, 20])], probe)
    assert out[0].stale is True


def test_entry_without_node_id_left_untouched():
    out = verify_entries([_entry(None, None)], FakeProbe([]))
    assert out[0].stale is False
