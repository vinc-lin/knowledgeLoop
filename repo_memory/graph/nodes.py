"""Adapt CBM graph results into M1 NodeRecords and enumerate per file."""

from __future__ import annotations

import re
from typing import Iterable, Optional

from repo_memory.bridge.schema import NodeRecord
from repo_memory.graph import forward


def row_to_node(row: dict) -> NodeRecord:
    """A CBM search_graph result row -> NodeRecord (node_id = qualified_name)."""
    qn = row.get("qualified_name") or row.get("name", "")
    return NodeRecord(
        node_id=qn,
        name=row.get("name", ""),
        qualified_name=qn,
        file_path=row.get("file_path", ""),
        start_line=int(row.get("start_line") or 0),
        end_line=int(row.get("end_line") or 0),
    )


def _rows(resp) -> list:
    return resp.get("results", []) if isinstance(resp, dict) else []


async def enumerate_nodes_for_files(client, files: list[str], *,
                                    page_size: int = 200) -> list[NodeRecord]:
    """Fetch all graph nodes located in the given files, deduped by qualified_name."""
    seen: dict[str, NodeRecord] = {}
    for path in files:
        offset = 0
        while True:
            resp = await forward.search_graph(client, file_pattern=path,
                                              limit=page_size, offset=offset)
            rows = _rows(resp)
            for row in rows:
                node = row_to_node(row)
                if node.qualified_name:
                    seen[node.qualified_name] = node
            if len(rows) < page_size or not (isinstance(resp, dict) and resp.get("has_more")):
                break
            offset += page_size
    return list(seen.values())


class CBMGraphProbe:
    """Synchronous M1 GraphProbe backed by a prefetched CBM cache."""

    def __init__(self, client):
        self._client = client
        self._cache: dict[str, NodeRecord] = {}

    async def prefetch(self, qns: Iterable[str]) -> None:
        for qn in qns:
            if qn in self._cache:
                continue
            node = await self._lookup_remote(qn)
            if node is not None:
                self._cache[qn] = node

    def lookup(self, node_id: str) -> Optional[NodeRecord]:
        return self._cache.get(node_id)

    async def _lookup_remote(self, qn: str) -> Optional[NodeRecord]:
        short = qn.rsplit(".", 1)[-1]
        resp = await forward.search_graph(self._client, name_pattern=f"^{re.escape(short)}$")
        for row in _rows(resp):
            if (row.get("qualified_name") or row.get("name")) == qn:
                return row_to_node(row)
        return None
