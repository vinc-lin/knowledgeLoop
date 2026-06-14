# Design Spec: repo_memory M5 — Deterministic Routing-Eval Harness

- **Date:** 2026-06-14
- **Parent spec:** `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md` (M0–M5)
- **Builds on:** M0–M4 (branch `feat/repo-memory-m0-m1`) — the 12-tool unified MCP facade with
  description-based routing (no server-side classifier; D4).
- **Status:** Draft for user review (design approved). This is the final, optional milestone.

---

## 1. Context & Scope

M3/M4 chose **description-based routing**: the calling LLM picks a tool from each tool's
routing-aware description, with no server-side classifier (the parent spec's routing decision: add
a classifier only if evals show frequent tool-selection errors). M5 builds the **deterministic
routing-eval harness**
that makes that routing intent explicit and regression-guarded.

**In scope:** a golden `(question → expected_tool, cue)` dataset + an offline, deterministic check
that each expected tool's description carries its routing cue, plus a coverage check that every
tool has ≥1 case.

**Out of scope (deferred / dropped, per the scope decision):** the server-side **classifier**
(stays deferred per D4 — only if a real eval shows errors), the **reranker**, and the
**agent-utility evaluation** (token-savings / answer-quality). The LLM-in-the-loop accuracy eval is
not built now, but the golden dataset is structured so it can be reused for one later.

## 2. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Cue-in-description** deterministic check (offline) | A CI-able proxy for routing: if a description loses its routing cue, the test fails. No LLM, no network. |
| D2 | Golden set lives in a **reusable module** (`routing_eval.py`), not inline in the test | A future LLM-in-loop eval imports the same `GOLDEN` dataset. |
| D3 | **Normal offline CI test** (not marker-gated) | Deterministic + fast → should run in the default suite as a regression guard. |
| D4 | **Coverage**: every tool in `TOOL_NAMES` must be the `expected_tool` of ≥1 golden case | Forces a routing case for any newly-added tool. |
| D5 | Classifier / reranker / agent-utility eval **deferred** | YAGNI for an optional milestone; classifier gated on a real eval (parent D4). |

## 3. Components

```
repo_memory/
└── routing_eval.py     # NEW: GOLDEN dataset + check_routing() (pure, reusable)
tests/
└── test_rm_routing.py  # NEW: app-level routing assertion + coverage + check_routing unit tests
```

No changes to existing modules. No new runtime dependencies.

## 4. `routing_eval.py`

```python
GOLDEN: list[dict]   # each: {"question": str, "expected_tool": str, "cue": str}
```
- `cue` is a phrase that MUST appear (case-insensitive) in `expected_tool`'s MCP description — the
  routing signal a competent LLM would key off. Examples:
  - `{"what does this change affect?", "assess_impact", "blast radius"}`
  - `{"how does chunking work, with proof?", "explain_with_sources", "graph-verified"}`
  - `{"where is the Foo class defined?", "search_code_graph", "locate exact symbols"}`
  - `{"who calls process_order?", "trace_symbol", "call paths"}`
  - `{"what's the overall architecture?", "get_repo_overview", "overall architecture"}`
  - `{"the graph is stale — fix it", "refresh_index", "re-index"}`
- ~1–2 cases per tool, covering all 12 tools' intents.

```python
def check_routing(descriptions: dict[str, str], cases: list[dict] = GOLDEN) -> list[str]:
    """Return a list of mismatch messages (empty == all routing cues present).

    For each case: if expected_tool not in descriptions -> mismatch;
    elif cue.lower() not in descriptions[expected_tool].lower() -> mismatch.
    Pure/synchronous — takes a {tool_name: description} mapping.
    """
```

## 5. `tests/test_rm_routing.py`

- **Routing check (app-level):** build the facade offline (`build_app(wiki_dir="x",
  entity_map_path="y")`), extract `{t.name: t.description for t in await app.list_tools()}`, assert
  `check_routing(descriptions) == []`.
- **Coverage (D4):** assert `{c["expected_tool"] for c in GOLDEN} == set(TOOL_NAMES)` (every tool
  covered; no case targets a non-existent tool).
- **`check_routing` unit tests:** a deliberately-wrong description (cue missing) → returns a
  mismatch naming the tool/cue; a correct mapping → returns `[]`; an unknown `expected_tool` →
  mismatch.

## 6. What It Guards / Why

The `GOLDEN` set is a **living spec of intended routing**. The CI test fails when:
- a tool's description is edited in a way that drops its routing cue (silent routing regression), or
- a new tool is added to `TOOL_NAMES` without a routing case (D4 coverage), or
- a case references a tool that no longer exists.

Offline, deterministic, fast. It does **not** prove an LLM routes correctly (that's the deferred
LLM-in-loop eval) — it guards that the routing *cues the LLM relies on* stay present and intentional.

## 7. Testing

The harness IS the test (`tests/test_rm_routing.py`). Plus the `check_routing` unit tests in §5.
Regression: full offline suite stays green; `pytest tests/test_rm_routing.py` runs with no network.

## 8. Internal Phases (of the M5 plan)

- **(a)** `routing_eval.py` — `GOLDEN` + `check_routing`, with `check_routing` unit tests.
- **(b)** `tests/test_rm_routing.py` — app-level routing assertion + coverage + offline gate.

## 9. Non-Goals (deferred)

Server-side routing classifier (parent D4 — only if a real eval shows errors); search-result
reranker; LLM-in-the-loop routing-accuracy eval; agent-utility (token-savings / answer-quality)
evaluation. The `GOLDEN` dataset is intentionally reusable by a future LLM eval.

## 10. Open Questions / Risks

- **Cue brittleness:** a cue must be a stable substring of a description. If descriptions are
  reworded, cues need updating — that's the *intended* signal (the test surfaces routing-relevant
  description changes), not a defect. Keep cues short and semantically central.
- **Coverage exactness:** D5/D4 uses set-equality (`expected_tools == TOOL_NAMES`); a tool with no
  natural single cue (e.g. `get_module_doc`) still needs a representative case.

### Related
- Parent: `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md`
- Builds on M2–M4 specs (facade / hybrid / freshness).
