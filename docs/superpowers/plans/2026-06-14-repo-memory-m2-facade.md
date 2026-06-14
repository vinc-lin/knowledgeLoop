# repo_memory M2: Unified MCP Facade (MVP) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `repo_memory` unified MCP server (MVP): basic Wiki tools, selected forwarded CBM graph tools, and `get_related_files` from the precomputed `entity_map.json` — all under one response contract, with stable CBM process management and graceful degradation.

**Architecture:** A FastMCP server fronts two backends: CodeWiki's generated docs (read from a manifest-anchored loader) and the Codebase-Memory-MCP graph (reached through a stdio `mcp` client that spawns `uvx codebase-memory-mcp`). Tool *logic* lives in plain functions taking an `AppState` (unit-testable offline against a mocked CBM client); thin `@app.tool` wrappers delegate to them. The M1 `bridge/` is reused unchanged via `NodeRecord.node_id = qualified_name`.

**Tech Stack:** Python 3.12, `mcp` SDK 1.27.2 (`ClientSession`/`stdio_client`/`StdioServerParameters` client, `FastMCP` server), pytest + pytest-asyncio (STRICT — async tests need `@pytest.mark.asyncio`), stdlib `json`/`asyncio`/`contextlib`. Builds on `feat/repo-memory-m0-m1`.

**Spec:** `docs/superpowers/specs/2026-06-14-repo-memory-m2-facade-design.md`. Conventions: line-length 100; `tests/` is gitignored → `git add -f` test files; unit tests offline, integration tests behind `@pytest.mark.integration`.

---

## File Structure

```
repo_memory/
├── graph/__init__.py
│   ├── client.py     # CBMUnavailable, parse_tool_result, backoff_delays, CBMClient
│   ├── forward.py    # thin async wrappers for selected + internal CBM tools
│   └── nodes.py      # row_to_node, enumerate_nodes_for_files, CBMGraphProbe
├── wiki/__init__.py
│   ├── loader.py     # WikiData, load_wiki (manifest-anchored)
│   └── search.py     # WikiIndex
├── contract.py       # envelope()
├── state.py          # AppState, load_app_state
├── entity_map_build.py  # build_and_save (offline)
├── tools/__init__.py
│   ├── wiki_tools.py    # get_repo_overview, list_modules, search_wiki, get_module_doc (logic)
│   ├── bridge_tools.py  # get_related_files (logic)
│   └── graph_tools.py   # search_code_graph, trace_symbol, get_code_snippet, get_architecture (logic)
└── server.py         # FastMCP app, lifespan, registers the 9 tools with descriptions
```

**Locked type contract (used across tasks):**
```python
# graph/client.py
class CBMUnavailable(RuntimeError): ...
def parse_tool_result(result) -> "Any"            # CallToolResult -> python payload
def backoff_delays(n, base=0.5, cap=8.0) -> list[float]
class CBMClient(command: list[str] | None = None, *, call_timeout: float = 30.0):
    async def start() -> None; running: bool
    async def call_tool(name: str, arguments: dict | None = None) -> "Any"
    async def call_tool_with_restart(name, arguments=None, *, max_restarts=2) -> "Any"
    async def aclose() -> None
# graph/forward.py  (all async, return parsed dict)
search_graph(client, *, name_pattern=None, label=None, file_pattern=None, limit=200, offset=0)
trace_path(client, *, function_name, direction="both", depth=3)
get_code_snippet(client, *, qualified_name)
get_architecture(client); get_graph_schema(client); index_status(client, *, project=None)
# graph/nodes.py
row_to_node(row: dict) -> NodeRecord               # node_id = qualified_name
async enumerate_nodes_for_files(client, files: list[str], *, page_size=200) -> list[NodeRecord]
class CBMGraphProbe(client): async prefetch(qns); lookup(node_id) -> NodeRecord | None  # sync lookup (M1-compatible)
# wiki/loader.py
@dataclass WikiData(module_tree: dict, metadata: dict, docs: dict[str,str], wiki_commit: str|None, files_generated: list[str])
load_wiki(wiki_dir: str) -> WikiData
# wiki/search.py: class WikiIndex(wiki): search(query, limit=10) -> list[dict]
# contract.py: envelope(result, *, freshness="unverified", provenance=None, confidence=None, warnings=None, unmatched=None) -> dict
# state.py: @dataclass AppState(wiki_dir, entity_map_path, repo_head=None, cbm=None, wiki=None, entity_map=None); load_app_state(...) -> AppState
# entity_map_build.py: async build_and_save(wiki, client, out_path, *, repo_root=None, repo_head=None) -> EntityMap
```

---

## Task 1: Scaffold `graph`/`wiki`/`tools` subpackages

**Files:** Create `repo_memory/graph/__init__.py`, `repo_memory/wiki/__init__.py`, `repo_memory/tools/__init__.py`; Modify `pyproject.toml`; Test `tests/test_rm_subpackages.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_subpackages.py
"""M2 subpackages are importable."""


def test_m2_subpackages_import():
    import repo_memory.graph  # noqa: F401
    import repo_memory.wiki  # noqa: F401
    import repo_memory.tools  # noqa: F401
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_subpackages.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.graph'`

- [ ] **Step 3: Create the three package markers**
```python
# repo_memory/graph/__init__.py
"""CBM graph access: stdio client, forwarded tools, node source + probe."""
```
```python
# repo_memory/wiki/__init__.py
"""CodeWiki generated-docs layer: manifest-anchored loader + search."""
```
```python
# repo_memory/tools/__init__.py
"""MCP tool logic (wiki / bridge / forwarded), returning the response envelope."""
```

- [ ] **Step 4: Register packages in pyproject**
In `pyproject.toml` `[tool.setuptools]` `packages`, after `"repo_memory.bridge"` add:
```toml
    "repo_memory.bridge",
    "repo_memory.graph",
    "repo_memory.wiki",
    "repo_memory.tools"
```

- [ ] **Step 5: Reinstall editable**
Run: `uv pip install --python .venv/bin/python -e ".[dev]"`
Expected: completes.

- [ ] **Step 6: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_subpackages.py -p no:cacheprovider --no-cov -q`
Expected: PASS

- [ ] **Step 7: Commit**
```bash
git add -f tests/test_rm_subpackages.py
git add repo_memory/graph/__init__.py repo_memory/wiki/__init__.py repo_memory/tools/__init__.py pyproject.toml
git commit -m "feat(repo_memory): scaffold graph/wiki/tools subpackages (M2)"
```

---

## Task 2: CBM result parsing + backoff helpers (pure)

**Files:** Create `repo_memory/graph/client.py`; Test `tests/test_rm_graph_client.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_graph_client.py
"""CBM client helpers + CBMClient behavior."""

import json
import pytest
from mcp.types import CallToolResult, TextContent

from repo_memory.graph.client import (
    CBMUnavailable, parse_tool_result, backoff_delays,
)


def _result(payload, is_error=False, structured=None):
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        isError=is_error, structuredContent=structured,
    )


def test_parse_prefers_structured_content():
    r = _result({"a": 1}, structured={"b": 2})
    assert parse_tool_result(r) == {"b": 2}


def test_parse_json_text():
    assert parse_tool_result(_result({"results": [1, 2]})) == {"results": [1, 2]}


def test_parse_raises_on_error():
    with pytest.raises(CBMUnavailable):
        parse_tool_result(_result({"msg": "boom"}, is_error=True))


def test_backoff_grows_and_caps():
    assert backoff_delays(1) == [0.5]
    assert backoff_delays(4) == [0.5, 1.0, 2.0, 4.0]
    assert backoff_delays(6, cap=4.0)[-1] == 4.0
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_client.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.graph.client'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/graph/client.py
"""Stdio MCP client for the Codebase-Memory-MCP backend."""

from __future__ import annotations

import json
from typing import Any, Optional


class CBMUnavailable(RuntimeError):
    """CBM is unreachable or returned an error."""


def parse_tool_result(result) -> Any:
    """Extract a CBM tool's payload from an mcp CallToolResult.

    Prefers structuredContent; else JSON-parses the first text block; else raw text.
    Raises CBMUnavailable if the result is flagged isError.
    """
    if getattr(result, "isError", False):
        raise CBMUnavailable(f"CBM tool error: {_first_text(result)}")
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    text = _first_text(result)
    if text is None:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _first_text(result) -> Optional[str]:
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return None


def backoff_delays(n: int, base: float = 0.5, cap: float = 8.0) -> list[float]:
    """Exponential backoff schedule: base, 2*base, 4*base, ... capped at `cap`."""
    return [min(cap, base * (2 ** i)) for i in range(n)]
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_client.py -p no:cacheprovider --no-cov -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_client.py
git add repo_memory/graph/client.py
git commit -m "feat(repo_memory): CBM result parsing + backoff helpers"
```

---

## Task 3: `CBMClient` — start / call_tool / aclose

**Files:** Modify `repo_memory/graph/client.py`; Modify `tests/test_rm_graph_client.py`

- [ ] **Step 1: Add failing tests**
Append to `tests/test_rm_graph_client.py`:
```python
from unittest.mock import AsyncMock
from repo_memory.graph.client import CBMClient


@pytest.mark.asyncio
async def test_call_tool_parses_and_passes_timeout():
    c = CBMClient(call_timeout=12.0)
    c._session = AsyncMock()
    c._session.call_tool = AsyncMock(return_value=_result({"ok": 1}))
    out = await c.call_tool("search_graph", {"label": "Function"})
    assert out == {"ok": 1}
    name, args = c._session.call_tool.await_args.args
    assert name == "search_graph"
    assert args == {"label": "Function"}
    kwargs = c._session.call_tool.await_args.kwargs
    assert kwargs["read_timeout_seconds"].total_seconds() == 12.0


@pytest.mark.asyncio
async def test_call_tool_without_session_raises():
    with pytest.raises(CBMUnavailable):
        await CBMClient().call_tool("x")


def test_default_command_is_uvx_cbm():
    c = CBMClient()
    assert c._params.command == "uvx"
    assert c._params.args == ["codebase-memory-mcp"]
```

- [ ] **Step 2: Run to verify the new tests fail**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_client.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError`/`ImportError` (CBMClient/`_params` not defined)

- [ ] **Step 3: Add `CBMClient` to `repo_memory/graph/client.py`**
Add these imports at the top (with the existing ones):
```python
from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_CBM_COMMAND = ["uvx", "codebase-memory-mcp"]
```
Append the class:
```python
class CBMClient:
    """Owns one long-lived CBM subprocess reached over stdio MCP."""

    def __init__(self, command: Optional[list[str]] = None, *, call_timeout: float = 30.0):
        cmd = command or DEFAULT_CBM_COMMAND
        self._params = StdioServerParameters(command=cmd[0], args=list(cmd[1:]))
        self._call_timeout = call_timeout
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None

    @property
    def running(self) -> bool:
        return self._session is not None

    async def start(self) -> None:
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(self._params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as exc:  # spawn/handshake failure
            await stack.aclose()
            raise CBMUnavailable(f"CBM start failed: {exc}") from exc
        self._stack, self._session = stack, session

    async def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        if self._session is None:
            raise CBMUnavailable("CBM client not started")
        result = await self._session.call_tool(
            name, arguments or {},
            read_timeout_seconds=timedelta(seconds=self._call_timeout),
        )
        return parse_tool_result(result)

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = self._session = None
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_client.py -p no:cacheprovider --no-cov -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_client.py
git add repo_memory/graph/client.py
git commit -m "feat(repo_memory): CBMClient stdio lifecycle (start/call_tool/aclose)"
```

---

## Task 4: `CBMClient.call_tool_with_restart` (auto-restart + backoff)

**Files:** Modify `repo_memory/graph/client.py`; Modify `tests/test_rm_graph_client.py`

- [ ] **Step 1: Add failing tests**
Append to `tests/test_rm_graph_client.py`:
```python
@pytest.mark.asyncio
async def test_restart_retries_then_succeeds(monkeypatch):
    c = CBMClient()
    c.call_tool = AsyncMock(side_effect=[CBMUnavailable("dropped"), {"ok": 1}])
    c._restart = AsyncMock()
    out = await c.call_tool_with_restart("search_graph", {"x": 1}, max_restarts=2)
    assert out == {"ok": 1}
    assert c._restart.await_count == 1


@pytest.mark.asyncio
async def test_restart_gives_up_after_max():
    c = CBMClient()
    c.call_tool = AsyncMock(side_effect=CBMUnavailable("dead"))
    c._restart = AsyncMock()
    with pytest.raises(CBMUnavailable):
        await c.call_tool_with_restart("x", max_restarts=2)
    assert c._restart.await_count == 2
```

- [ ] **Step 2: Run to verify the new tests fail**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_client.py -k restart -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: 'CBMClient' object has no attribute 'call_tool_with_restart'`

- [ ] **Step 3: Add the methods to `CBMClient`**
Add `import asyncio` to the top imports, then add these methods to `CBMClient`:
```python
    async def call_tool_with_restart(self, name: str, arguments: Optional[dict] = None,
                                     *, max_restarts: int = 2) -> Any:
        last: Optional[Exception] = None
        for attempt in range(max_restarts + 1):
            try:
                return await self.call_tool(name, arguments)
            except Exception as exc:
                last = exc
                if attempt < max_restarts:
                    await self._restart(attempt)
        raise CBMUnavailable(f"CBM call '{name}' failed after {max_restarts} restarts: {last}")

    async def _restart(self, attempt: int) -> None:
        await asyncio.sleep(backoff_delays(attempt + 1)[-1])
        await self.aclose()
        try:
            await self.start()
        except CBMUnavailable:
            pass  # next attempt's call_tool will raise "not started"
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_client.py -p no:cacheprovider --no-cov -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_client.py
git add repo_memory/graph/client.py
git commit -m "feat(repo_memory): CBM auto-restart with backoff on call failure"
```

---

## Task 5: Forwarded CBM tool wrappers

**Files:** Create `repo_memory/graph/forward.py`; Test `tests/test_rm_graph_forward.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_graph_forward.py
"""Thin async wrappers map to CBM tool names + args."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.graph import forward


def _client(ret):
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value=ret)
    return c


@pytest.mark.asyncio
async def test_search_graph_args():
    c = _client({"results": [], "total": 0, "has_more": False})
    out = await forward.search_graph(c, name_pattern=".*X", label="Function",
                                     file_pattern="a/b.py", limit=50, offset=10)
    assert out["total"] == 0
    name, args = c.call_tool_with_restart.await_args.args
    assert name == "search_graph"
    assert args == {"name_pattern": ".*X", "label": "Function",
                    "file_pattern": "a/b.py", "limit": 50, "offset": 10}


@pytest.mark.asyncio
async def test_search_graph_omits_none_filters():
    c = _client({"results": []})
    await forward.search_graph(c, label="Class")
    _, args = c.call_tool_with_restart.await_args.args
    assert args == {"label": "Class", "limit": 200, "offset": 0}


@pytest.mark.asyncio
async def test_trace_and_snippet_and_arch():
    c = _client({"r": 1})
    await forward.trace_path(c, function_name="main", direction="inbound", depth=2)
    assert c.call_tool_with_restart.await_args.args == (
        "trace_path", {"function_name": "main", "direction": "inbound", "depth": 2})
    await forward.get_code_snippet(c, qualified_name="proj.mod.Cls")
    assert c.call_tool_with_restart.await_args.args == (
        "get_code_snippet", {"qualified_name": "proj.mod.Cls"})
    await forward.get_architecture(c)
    assert c.call_tool_with_restart.await_args.args == ("get_architecture", {})
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_forward.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.graph.forward'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/graph/forward.py
"""Thin pass-through wrappers for the CBM tools we use. Single place that knows
CBM's tool names + argument keys, so schema drift is contained here."""

from __future__ import annotations

from typing import Any, Optional


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


async def search_graph(client, *, name_pattern: Optional[str] = None,
                       label: Optional[str] = None, file_pattern: Optional[str] = None,
                       limit: int = 200, offset: int = 0) -> Any:
    args = _compact({"name_pattern": name_pattern, "label": label,
                     "file_pattern": file_pattern})
    args.update({"limit": limit, "offset": offset})
    return await client.call_tool_with_restart("search_graph", args)


async def trace_path(client, *, function_name: str, direction: str = "both",
                     depth: int = 3) -> Any:
    return await client.call_tool_with_restart(
        "trace_path", {"function_name": function_name, "direction": direction, "depth": depth})


async def get_code_snippet(client, *, qualified_name: str) -> Any:
    return await client.call_tool_with_restart(
        "get_code_snippet", {"qualified_name": qualified_name})


async def get_architecture(client) -> Any:
    return await client.call_tool_with_restart("get_architecture", {})


async def get_graph_schema(client) -> Any:
    return await client.call_tool_with_restart("get_graph_schema", {})


async def index_status(client, *, project: Optional[str] = None) -> Any:
    return await client.call_tool_with_restart("index_status", _compact({"project": project}))
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_forward.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_forward.py
git add repo_memory/graph/forward.py
git commit -m "feat(repo_memory): forwarded CBM tool wrappers"
```

---

## Task 6: Node adapter + per-file enumeration

**Files:** Create `repo_memory/graph/nodes.py`; Test `tests/test_rm_graph_nodes.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_graph_nodes.py
"""CBM row -> NodeRecord and per-file enumeration with pagination."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.bridge.schema import NodeRecord
from repo_memory.graph.nodes import row_to_node, enumerate_nodes_for_files


def test_row_to_node_uses_qn_as_id():
    n = row_to_node({"name": "Cfg", "qualified_name": "p.m.Cfg",
                     "file_path": "p/m.py", "start_line": 3, "end_line": 9})
    assert n == NodeRecord("p.m.Cfg", "Cfg", "p.m.Cfg", "p/m.py", 3, 9)


def test_row_to_node_defaults_missing_lines():
    n = row_to_node({"name": "X", "qualified_name": "X", "file_path": "x.py"})
    assert n.start_line == 0 and n.end_line == 0


@pytest.mark.asyncio
async def test_enumerate_paginates_and_dedups():
    pages = [
        {"results": [{"name": "A", "qualified_name": "m.A", "file_path": "m.py",
                      "start_line": 1, "end_line": 2}], "has_more": True},
        {"results": [{"name": "A", "qualified_name": "m.A", "file_path": "m.py",
                      "start_line": 1, "end_line": 2},
                     {"name": "B", "qualified_name": "m.B", "file_path": "m.py",
                      "start_line": 3, "end_line": 4}], "has_more": False},
    ]
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(side_effect=pages)
    nodes = await enumerate_nodes_for_files(c, ["m.py"], page_size=1)
    qns = sorted(n.qualified_name for n in nodes)
    assert qns == ["m.A", "m.B"]  # deduped by qualified_name
    assert c.call_tool_with_restart.await_count == 2
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_nodes.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.graph.nodes'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/graph/nodes.py
"""Adapt CBM graph results into M1 NodeRecords and enumerate per file."""

from __future__ import annotations

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
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_nodes.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_nodes.py
git add repo_memory/graph/nodes.py
git commit -m "feat(repo_memory): CBM node adapter + per-file enumeration"
```

---

## Task 7: `CBMGraphProbe` (async prefetch + sync lookup)

**Files:** Modify `repo_memory/graph/nodes.py`; Modify `tests/test_rm_graph_nodes.py`

**Why prefetch+sync:** M1's `GraphProbe.lookup` is **synchronous**, but CBM calls are async. So the probe fetches the needed nodes asynchronously into a cache first, then `verify_entries` reads the cache synchronously. Serving code must `prefetch` the exact qualified-names it is about to verify, so a `None` from `lookup` means "genuinely absent" (→ stale), not "not fetched".

- [ ] **Step 1: Add failing tests**
Append to `tests/test_rm_graph_nodes.py`:
```python
from repo_memory.graph.nodes import CBMGraphProbe


@pytest.mark.asyncio
async def test_probe_prefetch_then_sync_lookup():
    found = {"results": [{"name": "Cfg", "qualified_name": "p.m.Cfg",
                          "file_path": "p/m.py", "start_line": 1, "end_line": 5}]}
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value=found)
    probe = CBMGraphProbe(c)
    await probe.prefetch(["p.m.Cfg"])
    node = probe.lookup("p.m.Cfg")
    assert node is not None and node.start_line == 1
    assert probe.lookup("p.m.Missing") is None  # not prefetched/found -> None


@pytest.mark.asyncio
async def test_probe_absent_node_not_cached():
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value={"results": []})
    probe = CBMGraphProbe(c)
    await probe.prefetch(["p.m.Gone"])
    assert probe.lookup("p.m.Gone") is None
```

- [ ] **Step 2: Run to verify the new tests fail**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_nodes.py -k probe -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError: cannot import name 'CBMGraphProbe'`

- [ ] **Step 3: Add `CBMGraphProbe` to `repo_memory/graph/nodes.py`**
Add `import re` to the top imports, then append:
```python
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
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_nodes.py -p no:cacheprovider --no-cov -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_nodes.py
git add repo_memory/graph/nodes.py
git commit -m "feat(repo_memory): CBMGraphProbe (async prefetch + M1-sync lookup)"
```

---

## Task 8: Manifest-anchored wiki loader

**Files:** Create `repo_memory/wiki/loader.py`; Test `tests/test_rm_wiki_loader.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_wiki_loader.py
"""Wiki loader reads ONLY codewiki-generated files (manifest-anchored)."""

import json
import os

from repo_memory.wiki.loader import load_wiki


def _write(d, rel, text):
    path = os.path.join(d, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _make_wiki(d):
    _write(d, "module_tree.json", json.dumps({"m": {"path": "p", "components": [], "children": {}}}))
    _write(d, "metadata.json", json.dumps({
        "generation_info": {"commit_id": "abc123"},
        "files_generated": ["overview.md", "m.md"],
    }))
    _write(d, "overview.md", "# Overview\n")
    _write(d, "m.md", "# Module m\n")
    # NON-generated noise that MUST be excluded:
    _write(d, "findings-and-practices.md", "hand notes\n")
    _write(d, "superpowers/specs/x-design.md", "a spec\n")


def test_loads_only_generated(tmp_path):
    _make_wiki(str(tmp_path))
    wiki = load_wiki(str(tmp_path))
    assert wiki.wiki_commit == "abc123"
    assert set(wiki.docs) == {"overview.md", "m.md"}
    assert "findings-and-practices.md" not in wiki.docs
    assert "superpowers/specs/x-design.md" not in wiki.docs
    assert wiki.module_tree["m"]["path"] == "p"


def test_missing_dir_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_wiki(str(tmp_path / "nope"))
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_loader.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.wiki.loader'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/wiki/loader.py
"""Load a codewiki-generated wiki, anchored on its generation manifest."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WikiData:
    module_tree: dict
    metadata: dict
    docs: dict          # filename -> markdown text (generated docs only)
    wiki_commit: Optional[str]
    files_generated: list = field(default_factory=list)


def load_wiki(wiki_dir: str) -> WikiData:
    """Read module_tree.json + metadata.json and ONLY the files metadata lists
    as generated. Non-generated markdown in the dir is ignored."""
    if not os.path.isdir(wiki_dir):
        raise FileNotFoundError(f"wiki dir not found: {wiki_dir}")
    with open(os.path.join(wiki_dir, "module_tree.json"), encoding="utf-8") as fh:
        module_tree = json.load(fh)
    with open(os.path.join(wiki_dir, "metadata.json"), encoding="utf-8") as fh:
        metadata = json.load(fh)
    files_generated = list(metadata.get("files_generated", []))
    commit = (metadata.get("generation_info") or {}).get("commit_id")
    docs: dict = {}
    for name in files_generated:
        if not name.endswith(".md"):
            continue
        path = os.path.join(wiki_dir, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                docs[name] = fh.read()
    return WikiData(module_tree=module_tree, metadata=metadata, docs=docs,
                    wiki_commit=commit, files_generated=files_generated)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_loader.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_wiki_loader.py
git add repo_memory/wiki/loader.py
git commit -m "feat(repo_memory): manifest-anchored wiki loader"
```

---

## Task 9: Wiki search index

**Files:** Create `repo_memory/wiki/search.py`; Test `tests/test_rm_wiki_search.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_wiki_search.py
"""Lightweight case-insensitive substring search over generated docs."""

from repo_memory.wiki.loader import WikiData
from repo_memory.wiki.search import WikiIndex


def _wiki():
    return WikiData(
        module_tree={}, metadata={},
        docs={"a.md": "# Ingestion\nThe chunker splits documents.",
              "b.md": "# Config\nSettings and flags."},
        wiki_commit=None, files_generated=["a.md", "b.md"],
    )


def test_search_finds_matching_doc():
    hits = WikiIndex(_wiki()).search("chunker")
    assert len(hits) == 1
    assert hits[0]["doc"] == "a.md"
    assert "chunker" in hits[0]["snippet"].lower()


def test_search_is_case_insensitive_and_limited():
    hits = WikiIndex(_wiki()).search("CONFIG", limit=5)
    assert hits and hits[0]["doc"] == "b.md"


def test_search_no_match_empty():
    assert WikiIndex(_wiki()).search("nonexistent") == []
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_search.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.wiki.search'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/wiki/search.py
"""Minimal substring search over generated wiki docs (MVP — no ranking model)."""

from __future__ import annotations


class WikiIndex:
    def __init__(self, wiki):
        self._docs = wiki.docs

    def search(self, query: str, limit: int = 10) -> list[dict]:
        q = query.lower().strip()
        hits: list[dict] = []
        if not q:
            return hits
        for name, text in self._docs.items():
            idx = text.lower().find(q)
            if idx != -1:
                start = max(0, idx - 60)
                snippet = text[start:idx + len(q) + 60].replace("\n", " ").strip()
                hits.append({"doc": name, "snippet": snippet})
            if len(hits) >= limit:
                break
        return hits
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_search.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_wiki_search.py
git add repo_memory/wiki/search.py
git commit -m "feat(repo_memory): wiki substring search index"
```

---

## Task 10: Offline entity-map build

**Files:** Create `repo_memory/entity_map_build.py`; Test `tests/test_rm_entity_map_build.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_entity_map_build.py
"""Offline build: enumerate nodes per module -> build_entity_map -> entity_map.json."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.wiki.loader import WikiData
from repo_memory.bridge.schema import load_entity_map
from repo_memory.entity_map_build import build_and_save


@pytest.mark.asyncio
async def test_build_and_save_grounds_known_symbol(tmp_path):
    wiki = WikiData(
        module_tree={"ingestion": {"path": "src/ingest",
                     "components": ["src/ingest/pipeline.py::Pipeline"], "children": {}}},
        metadata={}, docs={}, wiki_commit="wsha", files_generated=[],
    )
    client = AsyncMock()
    client.call_tool_with_restart = AsyncMock(return_value={"results": [
        {"name": "Pipeline", "qualified_name": "src.ingest.Pipeline",
         "file_path": "src/ingest/pipeline.py", "start_line": 1, "end_line": 20}]})
    out = tmp_path / "entity_map.json"
    em = await build_and_save(wiki, client, str(out), repo_head="rsha")
    assert out.exists()
    saved = load_entity_map(str(out))
    assert saved.built_at_repo_head == "rsha"
    assert saved.wiki_commit == "wsha"
    entry = saved.modules[0].entries[0]
    assert entry.match_strategy in ("exact", "qualified_suffix")
    assert entry.cbm_node_id == "src.ingest.Pipeline"
    assert em == saved
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_entity_map_build.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.entity_map_build'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/entity_map_build.py
"""Offline step: build the Wiki<->Graph entity_map.json from a wiki + CBM."""

from __future__ import annotations

from typing import Optional

from repo_memory.bridge.builder import _walk, _split_component, build_entity_map
from repo_memory.bridge.schema import save_entity_map, EntityMap, NodeRecord
from repo_memory.graph.nodes import enumerate_nodes_for_files


def _module_files(node: dict) -> list[str]:
    files = set()
    for component in node.get("components") or []:
        file, _symbol = _split_component(component)
        if file:
            files.add(file)
    return sorted(files)


async def build_and_save(wiki, client, out_path: str, *,
                         repo_root: Optional[str] = None,
                         repo_head: Optional[str] = None) -> EntityMap:
    # Collect the union of files referenced across all modules, enumerate once.
    all_files = set()
    for _name, node in _walk(wiki.module_tree):
        all_files.update(_module_files(node))
    nodes: list[NodeRecord] = await enumerate_nodes_for_files(client, sorted(all_files))
    em = build_entity_map(wiki.module_tree, nodes, repo_root=repo_root,
                          repo_head=repo_head, wiki_commit=wiki.wiki_commit)
    save_entity_map(em, out_path)
    return em
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_entity_map_build.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_entity_map_build.py
git add repo_memory/entity_map_build.py
git commit -m "feat(repo_memory): offline entity_map build wiring"
```

---

## Task 11: Response contract envelope

**Files:** Create `repo_memory/contract.py`; Test `tests/test_rm_contract.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_contract.py
"""The unified response envelope shape."""

from repo_memory.contract import envelope


def test_defaults():
    e = envelope({"x": 1})
    assert e["result"] == {"x": 1}
    assert e["freshness"] == "unverified"
    assert e["provenance"] == {"repo_head": None, "wiki_commit": None, "graph_commit": None}
    assert e["confidence"] is None
    assert e["warnings"] == []
    assert e["unmatched"] == []


def test_all_fields():
    e = envelope([], freshness="fresh",
                 provenance={"repo_head": "r", "wiki_commit": "w", "graph_commit": "g"},
                 confidence=0.9, warnings=["w1"], unmatched=[{"symbol": "S"}])
    assert e["freshness"] == "fresh"
    assert e["provenance"]["graph_commit"] == "g"
    assert e["confidence"] == 0.9
    assert e["warnings"] == ["w1"]
    assert e["unmatched"] == [{"symbol": "S"}]
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_contract.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.contract'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/contract.py
"""The unified response envelope returned by every repo_memory tool."""

from __future__ import annotations

from typing import Any, Optional

FRESHNESS = ("fresh", "stale-wiki", "stale-graph", "unverified")


def envelope(result: Any, *, freshness: str = "unverified",
             provenance: Optional[dict] = None, confidence: Optional[float] = None,
             warnings: Optional[list] = None, unmatched: Optional[list] = None) -> dict:
    return {
        "result": result,
        "freshness": freshness,
        "provenance": provenance or {"repo_head": None, "wiki_commit": None,
                                     "graph_commit": None},
        "confidence": confidence,
        "warnings": list(warnings or []),
        "unmatched": list(unmatched or []),
    }
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_contract.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_contract.py
git add repo_memory/contract.py
git commit -m "feat(repo_memory): unified response envelope"
```

---

## Task 12: App state + loader

**Files:** Create `repo_memory/state.py`; Test `tests/test_rm_state.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_state.py
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
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_state.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.state'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/state.py
"""Shared application state for the facade tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from repo_memory.wiki.loader import load_wiki, WikiData
from repo_memory.bridge.schema import load_entity_map, EntityMap


@dataclass
class AppState:
    wiki_dir: str
    entity_map_path: str
    repo_head: Optional[str] = None
    cbm: Optional[object] = None          # CBMClient | None (set by server lifespan)
    wiki: Optional[WikiData] = None
    entity_map: Optional[EntityMap] = None


def load_app_state(*, wiki_dir: str, entity_map_path: str,
                   repo_head: Optional[str] = None, cbm=None) -> AppState:
    """Load wiki + entity_map from disk; missing/unreadable artifacts degrade to None."""
    try:
        wiki = load_wiki(wiki_dir)
    except Exception:
        wiki = None
    try:
        entity_map = load_entity_map(entity_map_path)
    except Exception:
        entity_map = None
    return AppState(wiki_dir=wiki_dir, entity_map_path=entity_map_path,
                    repo_head=repo_head, cbm=cbm, wiki=wiki, entity_map=entity_map)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_state.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_state.py
git add repo_memory/state.py
git commit -m "feat(repo_memory): AppState + degrading loader"
```

---

## Task 13: Wiki tool logic

**Files:** Create `repo_memory/tools/wiki_tools.py`; Test `tests/test_rm_wiki_tools.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_wiki_tools.py
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
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_tools.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.tools.wiki_tools'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/tools/wiki_tools.py
"""Wiki tool logic (pure; take AppState, return the response envelope)."""

from __future__ import annotations

from typing import Optional

from repo_memory.contract import envelope
from repo_memory.wiki.search import WikiIndex


def provenance(state) -> dict:
    return {
        "repo_head": state.repo_head,
        "wiki_commit": state.wiki.wiki_commit if state.wiki else None,
        "graph_commit": state.entity_map.graph_commit if state.entity_map else None,
    }


def _no_wiki(state, empty):
    return envelope(empty, warnings=["wiki artifacts unavailable"],
                    provenance=provenance(state))


def _walk_modules(tree: dict):
    for name, node in tree.items():
        yield name, node
        yield from _walk_modules(node.get("children") or {})


def _find_module(tree: dict, module: str) -> Optional[dict]:
    for name, node in _walk_modules(tree):
        if name == module:
            return node
    return None


def get_repo_overview(state) -> dict:
    if not state.wiki:
        return _no_wiki(state, None)
    return envelope({"overview": state.wiki.docs.get("overview.md", ""),
                     "metadata": state.wiki.metadata}, provenance=provenance(state))


def list_modules(state) -> dict:
    if not state.wiki:
        return _no_wiki(state, [])
    return envelope([n for n, _ in _walk_modules(state.wiki.module_tree)],
                    provenance=provenance(state))


def search_wiki(state, query: str) -> dict:
    if not state.wiki:
        return _no_wiki(state, [])
    return envelope(WikiIndex(state.wiki).search(query), provenance=provenance(state))


def get_module_doc(state, module: str) -> dict:
    if not state.wiki:
        return _no_wiki(state, None)
    node = _find_module(state.wiki.module_tree, module)
    if node is None:
        return envelope(None, warnings=[f"module '{module}' not found"],
                        provenance=provenance(state))
    doc = state.wiki.docs.get(f"{module}.md", "")
    return envelope({"module": module, "path": node.get("path", ""),
                     "components": node.get("components", []), "doc": doc},
                    provenance=provenance(state))
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_tools.py -p no:cacheprovider --no-cov -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_wiki_tools.py
git add repo_memory/tools/wiki_tools.py
git commit -m "feat(repo_memory): wiki tool logic with provenance + degradation"
```

---

## Task 14: `get_related_files` (precomputed entity_map + verify-on-access)

**Files:** Create `repo_memory/tools/bridge_tools.py`; Test `tests/test_rm_bridge_tools.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_bridge_tools.py
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
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_bridge_tools.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.tools.bridge_tools'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/tools/bridge_tools.py
"""Bridge tool: get_related_files from the precomputed entity_map + verify-on-access."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from repo_memory.contract import envelope
from repo_memory.bridge.verify import verify_entries
from repo_memory.graph.nodes import CBMGraphProbe
from repo_memory.tools.wiki_tools import provenance


def _find_module(entity_map, module: str):
    for m in entity_map.modules:
        if m.module == module:
            return m
    return None


async def get_related_files(state, module: str, *, probe=None) -> dict:
    if state.entity_map is None:
        return envelope(None, warnings=["entity_map unavailable; run the build step"],
                        provenance=provenance(state))
    mod = _find_module(state.entity_map, module)
    if mod is None:
        return envelope(None, warnings=[f"module '{module}' not in entity_map"],
                        provenance=provenance(state))

    if probe is None:
        if state.cbm is None:
            # No graph to verify against: serve unverified, warn.
            files = sorted({e.file for e in mod.entries})
            return envelope(
                {"module": module, "files": files,
                 "entries": [asdict(e) for e in mod.entries]},
                warnings=["CBM unavailable; entries not verified"],
                confidence=_avg_conf(mod.entries), unmatched=[asdict(u) for u in mod.unmatched],
                provenance=provenance(state))
        probe = CBMGraphProbe(state.cbm)

    qns = [e.cbm_node_id for e in mod.entries if e.cbm_node_id]
    await probe.prefetch(qns)
    verify_entries(mod.entries, probe)
    any_stale = any(e.stale for e in mod.entries)
    files = sorted({e.file for e in mod.entries})
    return envelope(
        {"module": module, "files": files, "entries": [asdict(e) for e in mod.entries]},
        freshness=("stale-graph" if any_stale else "fresh"),
        confidence=_avg_conf(mod.entries),
        unmatched=[asdict(u) for u in mod.unmatched],
        provenance=provenance(state))


def _avg_conf(entries) -> Optional[float]:
    if not entries:
        return None
    return round(sum(e.confidence for e in entries) / len(entries), 3)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_bridge_tools.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_bridge_tools.py
git add repo_memory/tools/bridge_tools.py
git commit -m "feat(repo_memory): get_related_files (precomputed map + verify-on-access)"
```

---

## Task 15: Forwarded graph tool logic (with degradation)

**Files:** Create `repo_memory/tools/graph_tools.py`; Test `tests/test_rm_graph_tools.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_graph_tools.py
"""Forwarded graph tools wrap CBM results in the envelope; degrade when CBM is down."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.state import AppState
from repo_memory.graph.client import CBMUnavailable
from repo_memory.tools import graph_tools


def _state(cbm):
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=cbm)


@pytest.mark.asyncio
async def test_search_code_graph_wraps_result():
    cbm = AsyncMock()
    cbm.call_tool_with_restart = AsyncMock(return_value={"results": [{"name": "X"}], "total": 1})
    e = await graph_tools.search_code_graph(_state(cbm), name_pattern=".*X")
    assert e["result"]["total"] == 1
    assert e["provenance"]["repo_head"] == "r"


@pytest.mark.asyncio
async def test_degrades_when_cbm_none():
    e = await graph_tools.search_code_graph(_state(None), name_pattern=".*")
    assert e["result"] is None and e["warnings"]


@pytest.mark.asyncio
async def test_degrades_on_cbm_error():
    cbm = AsyncMock()
    cbm.call_tool_with_restart = AsyncMock(side_effect=CBMUnavailable("down"))
    e = await graph_tools.trace_symbol(_state(cbm), function_name="main")
    assert e["result"] is None and any("CBM" in w for w in e["warnings"])
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_tools.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.tools.graph_tools'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/tools/graph_tools.py
"""Forwarded CBM graph tools, wrapped in the response envelope with degradation."""

from __future__ import annotations

from repo_memory.contract import envelope
from repo_memory.graph import forward
from repo_memory.graph.client import CBMUnavailable
from repo_memory.tools.wiki_tools import provenance


async def _run(state, coro_factory):
    if state.cbm is None:
        return envelope(None, warnings=["CBM unavailable"], provenance=provenance(state))
    try:
        result = await coro_factory(state.cbm)
    except CBMUnavailable as exc:
        return envelope(None, warnings=[f"CBM error: {exc}"], provenance=provenance(state))
    return envelope(result, provenance=provenance(state))


async def search_code_graph(state, *, name_pattern=None, label=None,
                            file_pattern=None, limit=200, offset=0) -> dict:
    return await _run(state, lambda c: forward.search_graph(
        c, name_pattern=name_pattern, label=label, file_pattern=file_pattern,
        limit=limit, offset=offset))


async def trace_symbol(state, *, function_name, direction="both", depth=3) -> dict:
    return await _run(state, lambda c: forward.trace_path(
        c, function_name=function_name, direction=direction, depth=depth))


async def get_code_snippet(state, *, qualified_name) -> dict:
    return await _run(state, lambda c: forward.get_code_snippet(c, qualified_name=qualified_name))


async def get_architecture(state) -> dict:
    return await _run(state, lambda c: forward.get_architecture(c))
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_tools.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_tools.py
git add repo_memory/tools/graph_tools.py
git commit -m "feat(repo_memory): forwarded graph tool logic with degradation"
```

---

## Task 16: FastMCP facade server

**Files:** Create `repo_memory/server.py`; Test `tests/test_rm_server.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_server.py
"""The facade registers all 9 tools with non-empty descriptions."""

import pytest

from repo_memory.server import build_app, TOOL_NAMES


@pytest.mark.asyncio
async def test_registers_nine_named_tools():
    app = build_app(wiki_dir="w", entity_map_path="e", repo_head="r")
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert names == set(TOOL_NAMES)
    assert len(TOOL_NAMES) == 9
    for t in tools:
        assert t.description and len(t.description) > 20  # routing-aware descriptions
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_server.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.server'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/server.py
"""repo_memory unified MCP facade (FastMCP). Sole endpoint the agent calls."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP

from repo_memory.state import load_app_state
from repo_memory.graph.client import CBMClient
from repo_memory.tools import wiki_tools, bridge_tools, graph_tools

TOOL_NAMES = [
    "get_repo_overview", "list_modules", "search_wiki", "get_module_doc",
    "get_related_files",
    "search_code_graph", "trace_symbol", "get_code_snippet", "get_architecture",
]


def build_app(*, wiki_dir: str, entity_map_path: str,
              repo_head: Optional[str] = None,
              cbm_command: Optional[list] = None) -> FastMCP:
    state = load_app_state(wiki_dir=wiki_dir, entity_map_path=entity_map_path,
                           repo_head=repo_head)

    @asynccontextmanager
    async def lifespan(_app):
        client = CBMClient(cbm_command)
        try:
            await client.start()
            state.cbm = client
        except Exception:
            state.cbm = None  # degrade: wiki tools still work
        try:
            yield {}
        finally:
            await client.aclose()

    app = FastMCP("repo_memory",
                  instructions="Grounded code intelligence: CodeWiki docs + CBM graph.",
                  lifespan=lifespan)

    @app.tool(name="get_repo_overview",
              description="High-level repo overview from the generated wiki. Use FIRST for "
                          "'what is this project / overall architecture' questions.")
    def _overview() -> dict:
        return wiki_tools.get_repo_overview(state)

    @app.tool(name="list_modules",
              description="List the wiki module names. Use to discover module boundaries.")
    def _list() -> dict:
        return wiki_tools.list_modules(state)

    @app.tool(name="search_wiki",
              description="Search the generated module docs by keyword. Use for "
                          "conceptual 'how does X work / which module does Y' questions.")
    def _search_wiki(query: str) -> dict:
        return wiki_tools.search_wiki(state, query)

    @app.tool(name="get_module_doc",
              description="Get one module's generated doc, path, and components.")
    def _module_doc(module: str) -> dict:
        return wiki_tools.get_module_doc(state, module)

    @app.tool(name="get_related_files",
              description="Map a wiki module to its real source files + symbols (graph-"
                          "verified). Use to go from understanding a module to its code.")
    async def _related(module: str) -> dict:
        return await bridge_tools.get_related_files(state, module)

    @app.tool(name="search_code_graph",
              description="Structural code search over the CBM graph (name/label/file). "
                          "Use to locate exact symbols.")
    async def _search_graph(name_pattern: str = None, label: str = None,
                            file_pattern: str = None, limit: int = 200) -> dict:
        return await graph_tools.search_code_graph(
            state, name_pattern=name_pattern, label=label,
            file_pattern=file_pattern, limit=limit)

    @app.tool(name="trace_symbol",
              description="Trace a function's call paths (callers/callees) via the graph. "
                          "Use for call-chain questions.")
    async def _trace(function_name: str, direction: str = "both", depth: int = 3) -> dict:
        return await graph_tools.trace_symbol(
            state, function_name=function_name, direction=direction, depth=depth)

    @app.tool(name="get_code_snippet",
              description="Fetch source for a symbol by qualified name from the graph.")
    async def _snippet(qualified_name: str) -> dict:
        return await graph_tools.get_code_snippet(state, qualified_name=qualified_name)

    @app.tool(name="get_architecture",
              description="Graph-level architecture summary (languages, entry points, "
                          "hotspots) from CBM.")
    async def _arch() -> dict:
        return await graph_tools.get_architecture(state)

    return app


def main() -> None:  # pragma: no cover - process entry point
    wiki_dir = os.environ.get("REPO_MEMORY_WIKI_DIR", "docs")
    entity_map_path = os.environ.get("REPO_MEMORY_ENTITY_MAP", "entity_map.json")
    build_app(wiki_dir=wiki_dir, entity_map_path=entity_map_path).run(transport="stdio")
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_server.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_server.py
git add repo_memory/server.py
git commit -m "feat(repo_memory): FastMCP facade server with 9 tools + descriptions"
```

---

## Task 17: Integration test (gated) + milestone gate

**Files:** Create `tests/test_rm_integration.py`; Modify `pyproject.toml` (register the `integration` marker)

- [ ] **Step 1: Register the marker**
In `pyproject.toml` `[tool.pytest.ini_options]`, add:
```toml
markers = ["integration: needs network (uvx) and a real CBM run"]
```

- [ ] **Step 2: Write the integration test**
```python
# tests/test_rm_integration.py
"""End-to-end against a real CBM via uvx. Gated: needs network + uvx.

Run explicitly with:  .venv/bin/python -m pytest tests/test_rm_integration.py -m integration
"""

import os
import shutil
import subprocess
import pytest

from repo_memory.graph.client import CBMClient
from repo_memory.graph.nodes import enumerate_nodes_for_files

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _repo_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cbm_roundtrip_and_enumeration():
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    client = CBMClient()
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"CBM unavailable: {exc}")
    try:
        # index this repo, then enumerate nodes for a known codewiki file
        await client.call_tool("index_repository", {"path": REPO_ROOT})
        nodes = await enumerate_nodes_for_files(
            client, ["codewiki/cli/models/config.py"])
        names = {n.name for n in nodes}
        assert "Configuration" in names  # known codewiki class is grounded
    finally:
        await client.aclose()
```

- [ ] **Step 3: Run the offline suite (integration auto-deselected unless -m integration)**
Run:
```bash
.venv/bin/python -m pytest \
  tests/test_rm_subpackages.py tests/test_rm_graph_client.py tests/test_rm_graph_forward.py \
  tests/test_rm_graph_nodes.py tests/test_rm_wiki_loader.py tests/test_rm_wiki_search.py \
  tests/test_rm_entity_map_build.py tests/test_rm_contract.py tests/test_rm_state.py \
  tests/test_rm_wiki_tools.py tests/test_rm_bridge_tools.py tests/test_rm_graph_tools.py \
  tests/test_rm_server.py -p no:cacheprovider --no-cov -q
```
Expected: all PASS.

- [ ] **Step 4: Regression — full suite (offline)**
Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -q -m "not integration"`
Expected: all PASS (M1 + M2 unit tests; pre-existing tests unaffected). If the run hits the known pytest capture-teardown quirk, re-run with `-s`.

- [ ] **Step 5: (Optional, manual) run the gated integration test**
Run: `.venv/bin/python -m pytest tests/test_rm_integration.py -m integration -p no:cacheprovider --no-cov -q`
Expected: PASS, or SKIP if `uvx`/network/CBM is unavailable. **If it fails on a real shape mismatch** (e.g. `search_graph` rows lack `start_line`/`file_path`, or `index_repository` arg differs), that's the spec's open question surfacing — adjust `graph/nodes.py::row_to_node` / `graph/forward.py` and the affected unit tests, then re-commit.

- [ ] **Step 6: Commit**
```bash
git add -f tests/test_rm_integration.py
git add pyproject.toml
git commit -m "test(repo_memory): gated CBM integration test + offline M2 gate"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** transport/launch (Tasks 3,16) · per-module enumeration (Task 6) · `node_id=qualified_name` (Task 6) · manifest-anchored wiki (Task 8) · build-vs-serve (Task 10 build; Task 14 serve from precomputed map) · 9-tool surface (Tasks 13–16; count asserted in Task 16) · response contract on every tool (Task 11; used in 13–15) · CBM process mgmt incl. restart/backoff/timeout (Tasks 3,4) · graceful degradation both directions (Tasks 12 wiki-missing, 14/15 CBM-down) · clear descriptions (Task 16) · `graph_commit` recorded at build time (Task 10) · testing unit-offline + integration-marker (all tasks + Task 17). No spec requirement left unassigned.
- **Placeholder scan:** none — every code/test step is complete; every run step has a command + expected outcome. The integration test legitimately `skip`s when offline.
- **Type consistency:** `CBMClient.call_tool_with_restart`, `forward.*`, `row_to_node`, `enumerate_nodes_for_files`, `CBMGraphProbe.prefetch/lookup`, `WikiData`, `load_wiki`, `envelope`, `AppState`, `load_app_state`, `build_and_save`, `provenance`, `build_app`/`TOOL_NAMES` are named identically across tasks. `forward.*` calls `client.call_tool_with_restart` (the resilient path) consistently; `EntityEntry.cbm_node_id` holds the qualified name everywhere; envelope keys match Task 11 across all tools.
- **Known M3/M4 follow-ups (not gaps):** hybrid tools, Tier-B fail-closed, full `freshness` enum, automated refresh, module→doc-filename (`wiki_page`) derivation beyond the `{module}.md` best-effort in Task 13.
