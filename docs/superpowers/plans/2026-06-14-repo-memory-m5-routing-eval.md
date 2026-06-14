# repo_memory M5: Deterministic Routing-Eval Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, offline routing-eval harness — a golden `(question → expected_tool, cue)` dataset plus a check that every tool's MCP description still carries its routing cue, and that every tool is covered.

**Architecture:** A pure, reusable `repo_memory/routing_eval.py` (the `GOLDEN` dataset + `check_routing()`) and a test that builds the facade offline, pulls the 12 tool descriptions, and asserts no routing cue is missing + full coverage. No LLM, no network — a CI regression guard and a living spec of intended routing.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio (STRICT → the app-level test is `@pytest.mark.asyncio`). Builds on `feat/repo-memory-m0-m1` (12-tool facade). No new runtime deps.

**Spec:** `docs/superpowers/specs/2026-06-14-repo-memory-m5-routing-eval-design.md`. Conventions: line-length 100; `tests/` gitignored → `git add -f`; normal offline test (NOT marker-gated); transient `.git/index.lock` on commit → retry; do NOT stage `CLAUDE.md`, `.claude/`, or the concurrent `repo-memory-cbm-deploy-config` spec/plan.

**Cues are verified:** every `cue` below was confirmed to be a real case-insensitive substring of its tool's *current* description (extracted from `build_app().list_tools()`).

---

## File Structure

**Create:** `repo_memory/routing_eval.py` (`GOLDEN` + `check_routing`), `tests/test_rm_routing.py` (check_routing unit tests + app-level routing/coverage guards).
No changes to existing modules.

**Locked signatures:**
```python
GOLDEN: list[dict]    # each: {"question": str, "expected_tool": str, "cue": str}
def check_routing(descriptions: dict[str, str], cases: list[dict] = GOLDEN) -> list[str]
```

---

## Task 1: `routing_eval.py` — GOLDEN + `check_routing`

**Files:** Create `repo_memory/routing_eval.py`; Test `tests/test_rm_routing.py`

- [ ] **Step 1: Write the failing unit test**
```python
# tests/test_rm_routing.py
"""Deterministic routing eval: cues present in tool descriptions + coverage."""

from repo_memory.routing_eval import GOLDEN, check_routing


def test_check_routing_ok():
    descs = {"t": "this description mentions the blast radius clearly"}
    cases = [{"question": "q", "expected_tool": "t", "cue": "blast radius"}]
    assert check_routing(descs, cases) == []


def test_check_routing_reports_missing_cue():
    descs = {"t": "no routing signal here"}
    cases = [{"question": "q", "expected_tool": "t", "cue": "blast radius"}]
    m = check_routing(descs, cases)
    assert len(m) == 1 and "blast radius" in m[0] and "t" in m[0]


def test_check_routing_reports_unknown_tool():
    m = check_routing({}, [{"question": "q", "expected_tool": "ghost", "cue": "x"}])
    assert len(m) == 1 and "ghost" in m[0]


def test_check_routing_is_case_insensitive():
    descs = {"t": "Re-Index The Graph"}
    cases = [{"question": "q", "expected_tool": "t", "cue": "re-index"}]
    assert check_routing(descs, cases) == []


def test_golden_is_nonempty_and_well_formed():
    assert GOLDEN
    for c in GOLDEN:
        assert set(c) == {"question", "expected_tool", "cue"}
        assert c["question"] and c["expected_tool"] and c["cue"]
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_routing.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.routing_eval'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/routing_eval.py
"""Deterministic routing-eval harness.

GOLDEN is a living spec of intended tool routing: each case maps a representative
question to the tool that should handle it, plus a `cue` -- a phrase that must
appear in that tool's MCP description (the signal a competent LLM routes on).
check_routing() flags any tool whose description has dropped its cue, or any case
that targets a tool that doesn't exist. Pure/offline -- no LLM, no network.

Every cue is a real (case-insensitive) substring of its tool's current description.
"""

from __future__ import annotations

GOLDEN: list[dict] = [
    {"question": "What is this project's overall architecture?",
     "expected_tool": "get_repo_overview", "cue": "overall architecture"},
    {"question": "What are the module boundaries in this repo?",
     "expected_tool": "list_modules", "cue": "module boundaries"},
    {"question": "Which module handles request authentication?",
     "expected_tool": "search_wiki", "cue": "which module does"},
    {"question": "Show the doc, path, and components for the ingestion module.",
     "expected_tool": "get_module_doc", "cue": "path, and components"},
    {"question": "Which real source files implement the ingestion module?",
     "expected_tool": "get_related_files", "cue": "real source files"},
    {"question": "Find the exact symbol named ChunkStore.",
     "expected_tool": "search_code_graph", "cue": "locate exact symbols"},
    {"question": "Who calls process_order and what does it call?",
     "expected_tool": "trace_symbol", "cue": "call paths"},
    {"question": "Show the source for proj.mod.ChunkStore by its qualified name.",
     "expected_tool": "get_code_snippet", "cue": "qualified name"},
    {"question": "Give me a graph-level architecture summary with entry points.",
     "expected_tool": "get_architecture", "cue": "entry points"},
    {"question": "Explain how chunking works, with source-code proof.",
     "expected_tool": "explain_with_sources", "cue": "need proof"},
    {"question": "What is the blast radius of my current changes?",
     "expected_tool": "assess_impact", "cue": "blast radius"},
    {"question": "The graph is stale -- re-index it.",
     "expected_tool": "refresh_index", "cue": "re-index"},
]


def check_routing(descriptions: dict, cases: list = GOLDEN) -> list:
    """Return a list of mismatch messages (empty == every routing cue is present).

    A mismatch is reported when a case's expected_tool is absent from
    `descriptions`, or when its `cue` is not a (case-insensitive) substring of that
    tool's description.
    """
    mismatches: list = []
    for c in cases:
        tool = c["expected_tool"]
        if tool not in descriptions:
            mismatches.append(f"{tool}: not a registered tool (case: {c['question']!r})")
        elif c["cue"].lower() not in descriptions[tool].lower():
            mismatches.append(
                f"{tool}: routing cue {c['cue']!r} missing from description "
                f"(case: {c['question']!r})")
    return mismatches
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_routing.py -p no:cacheprovider --no-cov -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_routing.py
git add repo_memory/routing_eval.py
git commit -m "feat(repo_memory): routing-eval GOLDEN dataset + check_routing"
```

---

## Task 2: App-level routing + coverage guards

**Files:** Modify `tests/test_rm_routing.py`

These assert the harness against the *real* facade. They pass on the current (correct) descriptions — they are **regression guards**: they fail if a tool description is later edited to drop its cue, or a tool is added/removed without updating `GOLDEN`. (No separate red step — the guard is green on correct code; to see it bite, temporarily change a `GOLDEN` cue and watch it fail, then revert.)

- [ ] **Step 1: Append the app-level + coverage tests** to `tests/test_rm_routing.py`:
```python
import pytest

from repo_memory.server import build_app, TOOL_NAMES


@pytest.mark.asyncio
async def test_every_routing_cue_present_in_live_descriptions():
    app = build_app(wiki_dir="x", entity_map_path="y")
    tools = await app.list_tools()
    descriptions = {t.name: t.description for t in tools}
    assert check_routing(descriptions) == []


def test_golden_covers_every_registered_tool():
    # every tool has >=1 case AND no case targets a non-existent tool
    assert {c["expected_tool"] for c in GOLDEN} == set(TOOL_NAMES)
```

- [ ] **Step 2: Run the routing test file**
Run: `.venv/bin/python -m pytest tests/test_rm_routing.py -p no:cacheprovider --no-cov -q`
Expected: PASS (7 passed). If `test_every_routing_cue_present_in_live_descriptions` fails, a tool description no longer contains its `GOLDEN` cue — fix the cue (keep it a real substring) or the description. If `test_golden_covers_every_registered_tool` fails, a tool was added/removed without updating `GOLDEN`.

- [ ] **Step 3: Regression — full offline suite**
Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -q -m "not integration"`
Expected: all PASS. (If the pre-existing pytest capture-teardown error mangles the summary, re-run with `-s` and confirm "0 failed".)

- [ ] **Step 4: Commit**
```bash
git add -f tests/test_rm_routing.py
git commit -m "test(repo_memory): app-level routing-cue + coverage guards (M5)"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** `routing_eval.py` `GOLDEN` + `check_routing` (Task 1) · `check_routing` unit tests incl. missing-cue, unknown-tool, case-insensitive (Task 1) · app-level cue-present assertion via `build_app`/`list_tools` (Task 2) · coverage `{expected_tool} == set(TOOL_NAMES)` (Task 2) · offline/normal test, no marker, no new deps (both). Classifier/reranker/agent-utility remain deferred (spec §9). No spec item unassigned.
- **Cue validity:** all 12 cues were extracted-and-verified as case-insensitive substrings of the live descriptions (`get_repo_overview`→"overall architecture", `list_modules`→"module boundaries", `search_wiki`→"which module does", `get_module_doc`→"path, and components", `get_related_files`→"real source files", `search_code_graph`→"locate exact symbols", `trace_symbol`→"call paths", `get_code_snippet`→"qualified name", `get_architecture`→"entry points", `explain_with_sources`→"need proof", `assess_impact`→"blast radius", `refresh_index`→"re-index").
- **Placeholder scan:** none — complete code in every step; commands have expected outcomes. Task 2 has no artificial red step because it is a guard over existing-correct descriptions (noted explicitly).
- **Type consistency:** `GOLDEN` (list[dict] with keys question/expected_tool/cue), `check_routing(descriptions, cases=GOLDEN)->list[str]`, `build_app`/`TOOL_NAMES`/`list_tools()` used consistently with the M2/M4 server API.
