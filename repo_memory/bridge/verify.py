"""Verify-on-access: cheaply re-check entity entries against the live graph.

The graph is reached through an injected GraphProbe so this module has no
direct CBM dependency (the real probe is supplied by the M2 graph client).
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol

from repo_memory.bridge.schema import NodeRecord, EntityEntry


class GraphProbe(Protocol):
    def lookup(self, node_id: str) -> Optional[NodeRecord]: ...


def verify_entries(entries: Iterable[EntityEntry], probe: GraphProbe) -> list[EntityEntry]:
    """Mark entries stale when their backing node is gone or has moved.

    Entries with no ``cbm_node_id`` (file-only/unmatched) are left untouched.
    Mutates and returns the same EntityEntry objects.
    """
    result: list[EntityEntry] = []
    for e in entries:
        if e.cbm_node_id is not None:
            node = probe.lookup(e.cbm_node_id)
            if node is None:
                e.stale = True
            elif e.lines is not None and [node.start_line, node.end_line] != e.lines:
                e.stale = True
            else:
                e.stale = False
        result.append(e)
    return result
