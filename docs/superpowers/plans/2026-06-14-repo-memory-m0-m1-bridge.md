# repo_memory M0–M1: Scaffold + Bridge Keystone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the standalone-testable foundation of the `repo_memory` integration — the Wiki↔Graph entity-map builder + verify-on-access library — and make CodeWiki record the commit it documented.

**Architecture:** A new top-level Python package `repo_memory/` is added to this repo (the merge vehicle; product = knowledgeLoop). Milestone M1 is a **pure data-transformation library**: `build_entity_map()` joins CodeWiki's `module_tree.json` components (`file::Symbol`) against CBM graph nodes (`file_path`/`name`/`qualified_name`) into an `EntityMap`, and `verify_entries()` re-checks entries via an **injected `GraphProbe`** (no live CBM dependency yet — the real client arrives in M2). One small CodeWiki change populates `metadata.commit_id`, which all later freshness checks depend on.

**Tech Stack:** Python 3.12, dataclasses, stdlib `json`, pytest (flat `tests/`, `tmp_path`), GitPython (already used via `codewiki/cli/git_manager.py`). Black/Ruff line-length 100.

**Scope note:** This plan implements **M0 + M1 only** from `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md`. M2 (facade server + CBM client + forwarded/wiki tools), M3 (hybrid + routing), M4 (freshness/refresh/policy), and M5 (evals/extras) are **separate subsequent plans**, each building on this one.

---

## File Structure

**Created:**
- `repo_memory/__init__.py` — package marker (product: knowledgeLoop).
- `repo_memory/bridge/__init__.py` — bridge subpackage marker.
- `repo_memory/bridge/paths.py` — `normalize_path()`, `path_suffix_match()` (path reconciliation between CodeWiki repo-relative paths and CBM `file_path`).
- `repo_memory/bridge/schema.py` — dataclasses (`NodeRecord`, `EntityEntry`, `ModuleMap`, `EntityMap`), `CONFIDENCE` constants, `to_dict`/`from_dict`, `save_entity_map`/`load_entity_map`.
- `repo_memory/bridge/builder.py` — `build_entity_map()` (the deterministic join).
- `repo_memory/bridge/verify.py` — `GraphProbe` protocol + `verify_entries()` (verify-on-access).
- `tests/test_repo_memory_paths.py`, `tests/test_repo_memory_schema.py`, `tests/test_repo_memory_builder.py`, `tests/test_repo_memory_verify.py`, `tests/test_metadata_commit_id.py`.

**Modified:**
- `pyproject.toml` — add `repo_memory`, `repo_memory.bridge` to `[tool.setuptools].packages`.
- `codewiki/cli/adapters/doc_generator.py` — add `_resolve_commit_id()`; pass it to `DocumentationGenerator(...)`.

**Type contract locked here (used by all later milestones):**
```python
NodeRecord(node_id: str, name: str, qualified_name: str, file_path: str, start_line: int, end_line: int)  # frozen
EntityEntry(symbol: str, file: str, cbm_node_id: str|None, lines: list[int]|None, match_strategy: str, confidence: float, stale: bool=False)
ModuleMap(module: str, wiki_page: str|None, path: str, entries: list[EntityEntry], unmatched: list[EntityEntry])
EntityMap(built_at_repo_head: str|None, wiki_commit: str|None, graph_commit: str|None, modules: list[ModuleMap])
build_entity_map(module_tree: dict, nodes: Iterable[NodeRecord], *, repo_root: str|None=None, repo_head=None, wiki_commit=None, graph_commit=None) -> EntityMap
verify_entries(entries: Iterable[EntityEntry], probe: GraphProbe) -> list[EntityEntry]   # GraphProbe.lookup(node_id) -> NodeRecord|None
```
`match_strategy` ∈ `{"exact","qualified_suffix","file_only","unmatched"}`; `CONFIDENCE = {"exact":1.0,"qualified_suffix":0.85,"file_only":0.5,"unmatched":0.0}`.

---

## Task 1: Scaffold `repo_memory` package (M0)

**Files:**
- Create: `repo_memory/__init__.py`, `repo_memory/bridge/__init__.py`
- Modify: `pyproject.toml` (the `[tool.setuptools].packages` list)
- Test: `tests/test_repo_memory_import.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_memory_import.py
"""repo_memory package is importable after scaffold."""


def test_repo_memory_imports():
    import repo_memory  # noqa: F401
    import repo_memory.bridge  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_import.py -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory'`

- [ ] **Step 3: Create the package files**

```python
# repo_memory/__init__.py
"""repo_memory — unified MCP integration server (product: knowledgeLoop).

Fronts CodeWiki documentation + the Codebase-Memory-MCP code graph.
See docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md.
"""
```

```python
# repo_memory/bridge/__init__.py
"""Wiki<->Graph bridge: entity-map build + verify-on-access."""
```

- [ ] **Step 4: Register the packages in pyproject**

In `pyproject.toml`, inside `[tool.setuptools]` `packages = [ ... ]`, add these two lines after the `"codewiki.src.fe"` entry:

```toml
    "codewiki.src.fe",
    "repo_memory",
    "repo_memory.bridge"
```

(Add a trailing comma to the previous last entry if needed so the list stays valid TOML.)

- [ ] **Step 5: Reinstall editable so the new package is importable**

Run: `uv pip install --python .venv/bin/python -e ".[dev]"`
Expected: completes; `repo_memory` now on the path.

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_import.py -v -p no:cacheprovider --no-cov`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -f tests/test_repo_memory_import.py
git add repo_memory/__init__.py repo_memory/bridge/__init__.py pyproject.toml
git commit -m "feat(repo_memory): scaffold package (M0)"
```
(Note: `tests/` is gitignored in this repo — new test files need `git add -f`.)

---

## Task 2: Path reconciliation helpers

**Files:**
- Create: `repo_memory/bridge/paths.py`
- Test: `tests/test_repo_memory_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_memory_paths.py
"""Path normalization + suffix matching between CodeWiki and CBM paths."""

from repo_memory.bridge.paths import normalize_path, path_suffix_match


def test_normalize_passthrough_relative():
    assert normalize_path("codewiki/cli/x.py") == "codewiki/cli/x.py"


def test_normalize_strips_repo_root():
    assert normalize_path("/home/u/repo/codewiki/x.py", "/home/u/repo") == "codewiki/x.py"


def test_normalize_backslashes_and_root():
    assert normalize_path("C:\\repo\\a.py", "C:\\repo") == "a.py"


def test_normalize_strips_leading_dot_slash():
    assert normalize_path("./a.py") == "a.py"


def test_normalize_keeps_dotfile():
    assert normalize_path(".env.py") == ".env.py"


def test_suffix_match_shared_tail():
    assert path_suffix_match("codewiki/cli/x.py", "/abs/codewiki/cli/x.py") is True


def test_suffix_match_rejects_partial_segment():
    # "config.py" must NOT match "myconfig.py"
    assert path_suffix_match("a/config.py", "b/myconfig.py") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_paths.py -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.bridge.paths'`

- [ ] **Step 3: Write the implementation**

```python
# repo_memory/bridge/paths.py
"""Reconcile CodeWiki repo-relative paths with CBM file_path values."""

from __future__ import annotations


def normalize_path(path: str, repo_root: str | None = None) -> str:
    """Return a forward-slash, repo-relative path.

    Strips an absolute ``repo_root`` prefix when given, normalizes Windows
    separators, and removes a single leading ``./`` or ``/``.
    """
    p = path.replace("\\", "/")
    if repo_root:
        root = repo_root.replace("\\", "/").rstrip("/")
        if p.startswith(root + "/"):
            p = p[len(root) + 1:]
    if p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]
    return p


def path_suffix_match(a: str, b: str) -> bool:
    """True if the two paths share an identical trailing run of segments.

    Segment-aware so ``config.py`` does not match ``myconfig.py``.
    """
    pa = [s for s in a.split("/") if s]
    pb = [s for s in b.split("/") if s]
    if not pa or not pb:
        return False
    n = min(len(pa), len(pb))
    return pa[-n:] == pb[-n:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_paths.py -v -p no:cacheprovider --no-cov`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add -f tests/test_repo_memory_paths.py
git add repo_memory/bridge/paths.py
git commit -m "feat(repo_memory): path reconciliation helpers"
```

---

## Task 3: Entity-map schema + JSON (de)serialization

**Files:**
- Create: `repo_memory/bridge/schema.py`
- Test: `tests/test_repo_memory_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_memory_schema.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_schema.py -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.bridge.schema'`

- [ ] **Step 3: Write the implementation**

```python
# repo_memory/bridge/schema.py
"""Entity-map data model and JSON (de)serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional

CONFIDENCE = {"exact": 1.0, "qualified_suffix": 0.85, "file_only": 0.5, "unmatched": 0.0}


@dataclass(frozen=True)
class NodeRecord:
    """A code node as supplied by CBM (or a test fixture)."""
    node_id: str
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int


@dataclass
class EntityEntry:
    symbol: str
    file: str
    cbm_node_id: Optional[str]
    lines: Optional[list]          # [start, end] or None
    match_strategy: str            # exact | qualified_suffix | file_only | unmatched
    confidence: float
    stale: bool = False


@dataclass
class ModuleMap:
    module: str
    wiki_page: Optional[str]
    path: str
    entries: list = field(default_factory=list)      # list[EntityEntry]
    unmatched: list = field(default_factory=list)     # list[EntityEntry]


@dataclass
class EntityMap:
    built_at_repo_head: Optional[str]
    wiki_commit: Optional[str]
    graph_commit: Optional[str]
    modules: list = field(default_factory=list)       # list[ModuleMap]


def to_dict(em: EntityMap) -> dict:
    return asdict(em)


def _entry(d: dict) -> EntityEntry:
    return EntityEntry(
        symbol=d["symbol"], file=d["file"], cbm_node_id=d["cbm_node_id"],
        lines=d["lines"], match_strategy=d["match_strategy"],
        confidence=d["confidence"], stale=d.get("stale", False),
    )


def from_dict(d: dict) -> EntityMap:
    modules = [
        ModuleMap(
            module=m["module"], wiki_page=m["wiki_page"], path=m["path"],
            entries=[_entry(e) for e in m["entries"]],
            unmatched=[_entry(e) for e in m["unmatched"]],
        )
        for m in d["modules"]
    ]
    return EntityMap(
        built_at_repo_head=d["built_at_repo_head"],
        wiki_commit=d["wiki_commit"], graph_commit=d["graph_commit"],
        modules=modules,
    )


def save_entity_map(em: EntityMap, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_dict(em), fh, indent=2)


def load_entity_map(path: str) -> EntityMap:
    with open(path, encoding="utf-8") as fh:
        return from_dict(json.load(fh))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_schema.py -v -p no:cacheprovider --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add -f tests/test_repo_memory_schema.py
git add repo_memory/bridge/schema.py
git commit -m "feat(repo_memory): entity-map schema + JSON round-trip"
```

---

## Task 4: `build_entity_map` — exact match + unmatched

**Files:**
- Create: `repo_memory/bridge/builder.py`
- Test: `tests/test_repo_memory_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_memory_builder.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_builder.py -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.bridge.builder'`

- [ ] **Step 3: Write the implementation**

```python
# repo_memory/bridge/builder.py
"""Build an EntityMap by joining a CodeWiki module_tree against CBM nodes."""

from __future__ import annotations

from typing import Iterable, Optional

from repo_memory.bridge.paths import normalize_path, path_suffix_match
from repo_memory.bridge.schema import (
    CONFIDENCE, NodeRecord, EntityEntry, ModuleMap, EntityMap,
)


def _walk(tree: dict):
    """Yield (module_name, node) for every module in the tree, depth-first."""
    for name, node in tree.items():
        yield name, node
        for pair in _walk(node.get("children") or {}):
            yield pair


def _split_component(component: str) -> tuple[str, str]:
    """'path/to/file.py::Symbol' -> ('path/to/file.py', 'Symbol')."""
    if "::" in component:
        file, symbol = component.rsplit("::", 1)
        return file, symbol
    return component, ""


def _match(file: str, symbol: str, nodes: list[NodeRecord],
           repo_root: Optional[str]) -> EntityEntry:
    nf = normalize_path(file, repo_root)
    by_name = [n for n in nodes if n.name == symbol]
    # 1. exact: same normalized file + same name
    for n in by_name:
        if normalize_path(n.file_path, repo_root) == nf:
            return EntityEntry(symbol, nf, n.node_id, [n.start_line, n.end_line],
                               "exact", CONFIDENCE["exact"])
    # 2. qualified_suffix: same name, shared path tail (handles differing roots)
    for n in by_name:
        if path_suffix_match(nf, normalize_path(n.file_path, repo_root)):
            return EntityEntry(symbol, nf, n.node_id, [n.start_line, n.end_line],
                               "qualified_suffix", CONFIDENCE["qualified_suffix"])
    # 3. file_only: the file exists in the graph but the symbol does not
    for n in nodes:
        nfp = normalize_path(n.file_path, repo_root)
        if nfp == nf or path_suffix_match(nf, nfp):
            return EntityEntry(symbol, nf, None, None,
                               "file_only", CONFIDENCE["file_only"])
    # 4. unmatched
    return EntityEntry(symbol, nf, None, None, "unmatched", CONFIDENCE["unmatched"])


def build_entity_map(module_tree: dict, nodes: Iterable[NodeRecord], *,
                     repo_root: Optional[str] = None,
                     repo_head: Optional[str] = None,
                     wiki_commit: Optional[str] = None,
                     graph_commit: Optional[str] = None) -> EntityMap:
    node_list = list(nodes)
    modules: list[ModuleMap] = []
    for name, node in _walk(module_tree):
        mod = ModuleMap(module=name, wiki_page=None, path=node.get("path", ""))
        for component in node.get("components") or []:
            file, symbol = _split_component(component)
            if not symbol:
                continue
            entry = _match(file, symbol, node_list, repo_root)
            if entry.match_strategy == "unmatched":
                mod.unmatched.append(entry)
            else:
                mod.entries.append(entry)
        modules.append(mod)
    return EntityMap(built_at_repo_head=repo_head, wiki_commit=wiki_commit,
                     graph_commit=graph_commit, modules=modules)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_builder.py -v -p no:cacheprovider --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add -f tests/test_repo_memory_builder.py
git add repo_memory/bridge/builder.py
git commit -m "feat(repo_memory): build_entity_map exact match + unmatched + tree walk"
```

---

## Task 5: `build_entity_map` — qualified-suffix & file-only fallbacks

**Files:**
- Modify: `tests/test_repo_memory_builder.py` (add cases — implementation from Task 4 already covers these; this task proves the fallbacks)

- [ ] **Step 1: Add failing tests for the fallback strategies**

Append to `tests/test_repo_memory_builder.py`:

```python
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
```

- [ ] **Step 2: Run the new tests**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_builder.py -v -p no:cacheprovider --no-cov`
Expected: PASS (4 passed). If exact precedence is wrong, the `qualified_suffix`/`file_only` assertions will catch it.

- [ ] **Step 3: Adjust `builder._match` only if a test fails**

The Task 4 implementation already orders exact → qualified_suffix → file_only → unmatched. If a test fails, the bug is in that ordering in `repo_memory/bridge/builder.py::_match`; fix the ordering so the four strategies are evaluated in that exact sequence. (No change expected.)

- [ ] **Step 4: Commit**

```bash
git add -f tests/test_repo_memory_builder.py
git commit -m "test(repo_memory): cover qualified-suffix and file-only match fallbacks"
```

---

## Task 6: `verify_entries` — verify-on-access via injected probe

**Files:**
- Create: `repo_memory/bridge/verify.py`
- Test: `tests/test_repo_memory_verify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_memory_verify.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_verify.py -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.bridge.verify'`

- [ ] **Step 3: Write the implementation**

```python
# repo_memory/bridge/verify.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_repo_memory_verify.py -v -p no:cacheprovider --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add -f tests/test_repo_memory_verify.py
git add repo_memory/bridge/verify.py
git commit -m "feat(repo_memory): verify-on-access via injected GraphProbe"
```

---

## Task 7: CodeWiki records the documented commit (`metadata.commit_id`)

**Files:**
- Modify: `codewiki/cli/adapters/doc_generator.py` (add `_resolve_commit_id`; pass it at the `DocumentationGenerator(...)` call, currently line ~192)
- Test: `tests/test_metadata_commit_id.py`

**Context:** `DocumentationGenerator.__init__(self, config, commit_id=None, backend=None)` already writes `commit_id` into `metadata.json`'s `generation_info`. The CLI adapter constructs it as `DocumentationGenerator(backend_config)` (no commit), so `metadata.commit_id` is `null`. `GitManager(path).get_commit_hash()` (in `codewiki/cli/git_manager.py`) returns the HEAD sha via GitPython and raises off a git repo — so guard it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metadata_commit_id.py
"""_resolve_commit_id returns the repo HEAD sha, or None off a git repo."""

import os
import re

from codewiki.cli.adapters.doc_generator import _resolve_commit_id

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_returns_sha_for_real_repo():
    sha = _resolve_commit_id(REPO_ROOT)
    assert sha is not None
    assert re.fullmatch(r"[0-9a-f]{40}", sha)


def test_returns_none_for_non_git_dir(tmp_path):
    assert _resolve_commit_id(str(tmp_path)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_metadata_commit_id.py -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ImportError: cannot import name '_resolve_commit_id'`

- [ ] **Step 3: Add `_resolve_commit_id` to the adapter**

In `codewiki/cli/adapters/doc_generator.py`, add this module-level function after the imports (after line ~23):

```python
def _resolve_commit_id(repo_path) -> "str | None":
    """Best-effort current commit sha of the repo being documented.

    Returns None when repo_path is not a git repository.
    """
    try:
        from codewiki.cli.git_manager import GitManager
        return GitManager(Path(repo_path)).get_commit_hash()
    except Exception:
        return None
```

- [ ] **Step 4: Pass the commit id at construction**

In `codewiki/cli/adapters/doc_generator.py`, replace the line (~192):

```python
        doc_generator = DocumentationGenerator(backend_config)
```

with:

```python
        commit_id = _resolve_commit_id(self.repo_path)
        doc_generator = DocumentationGenerator(backend_config, commit_id=commit_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_metadata_commit_id.py -v -p no:cacheprovider --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add -f tests/test_metadata_commit_id.py
git add codewiki/cli/adapters/doc_generator.py
git commit -m "fix(codewiki): record documented commit in metadata.commit_id"
```

---

## Task 8: Full-suite gate for the milestone

**Files:** none (verification only)

- [ ] **Step 1: Run the whole repo_memory + metadata test set**

Run:
```bash
.venv/bin/python -m pytest \
  tests/test_repo_memory_import.py tests/test_repo_memory_paths.py \
  tests/test_repo_memory_schema.py tests/test_repo_memory_builder.py \
  tests/test_repo_memory_verify.py tests/test_metadata_commit_id.py \
  -v -p no:cacheprovider --no-cov
```
Expected: all PASS.

- [ ] **Step 2: Run the existing suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider`
Expected: existing tests still PASS (the codewiki change only adds a guarded helper and one constructor argument).

- [ ] **Step 3: Sanity-check the join against a real corpus (manual)**

Run:
```bash
.venv/bin/python -c "
import json
from repo_memory.bridge.builder import build_entity_map
tree = json.load(open('docs/module_tree.json'))
em = build_entity_map(tree, [])   # no nodes -> everything is unmatched
total = sum(len(m.unmatched) for m in em.modules)
print('modules:', len(em.modules), 'components(all unmatched w/o graph):', total)
"
```
Expected: prints a module count > 0 and a component count > 0 — confirms `module_tree.json` parses and the walker traverses it. (Grounding-rate assertions against a live CBM `.db` belong to M2.)

- [ ] **Step 4: Commit (if any incidental fixes were needed)**

```bash
git commit -am "test(repo_memory): M0-M1 milestone green" --allow-empty
```

---

## Self-Review (completed by plan author)

- **Spec coverage (M0–M1 scope):** M0 scaffold → Task 1. M1 entity-map builder → Tasks 3–5; verify-on-access → Task 6; `entity_map.json` artifact (de)serialization → Task 3; `metadata.commit_id` fix → Task 7. Path-normalization risk (spec §13) → Task 2. M2–M5 are explicitly deferred to later plans (stated in Scope note). No M0–M1 requirement left unassigned.
- **Placeholder scan:** none — every code/test step contains complete code; every run step has an exact command + expected outcome.
- **Type consistency:** `NodeRecord`, `EntityEntry` (with `lines: list|None`, `stale`), `ModuleMap`, `EntityMap`, `CONFIDENCE`, `build_entity_map(...)`, `verify_entries(...)`, `GraphProbe.lookup`, `normalize_path`, `path_suffix_match`, `_resolve_commit_id` are named identically across the File-Structure contract, tasks, and tests. `lines` is `[start, end]` everywhere (JSON-safe; no tuples).
- **Known follow-ups for M2 (not gaps here):** real CBM stdio client supplying `nodes` to `build_entity_map` and a concrete `GraphProbe`; deriving `ModuleMap.wiki_page` from canonicalized doc filenames; computing the `freshness` enum from `verify_entries` output + the three commit ids.
