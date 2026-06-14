# Design Spec: repo_memory M4 — Freshness, Two-Tier Policy & Bounded Refresh

- **Date:** 2026-06-14
- **Parent spec:** `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md` (M0–M5)
- **Builds on:** M0–M3 (branch `feat/repo-memory-m0-m1`) — bridge keystone, unified facade
  (11 tools), hybrid fusion (`explain_with_sources`, fail-closed `assess_impact`).
- **Status:** Draft for user review (design approved).

---

## 1. Context & Scope

M2/M3 set the response `freshness` field ad-hoc per tool and made only `assess_impact`
fail-closed. M4 makes freshness/safety real and recoverable:

1. **Central freshness enum** — one `compute_freshness(state)` reused by all tools, distinguishing
   `stale-wiki` (docs behind code) from `stale-graph` (graph behind code).
2. **General two-tier policy** — a shared `require_fresh(state)` gate; read-only tools warn,
   high-risk (Tier-B) tools fail closed.
3. **Bounded refresh** — re-index CBM + rebuild the entity_map to restore graph-freshness.

**Latent gap this milestone fixes:** `build_and_save` never records `graph_commit` (it defaults to
`None`), so `grounding.graph_is_current` is always False in production and **`assess_impact` would
fail-closed-block on every real call**. M4 records `graph_commit` so freshness actually works.

**In scope:** the three items above. **Out of scope (deferred):** LLM **wiki regeneration**
orchestration (stale-wiki is *detected*; the user re-runs `codewiki generate` manually); routing
eval harness + server-side classifier + agent-utility evaluation (the old M5).

## 2. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Central `compute_freshness(state, *, entries_stale=False)`; precedence **graph > wiki** | Graph is the verification substrate; its staleness is the more safety-critical signal |
| D2 | `require_fresh(state)` is **graph-only** (reuses `graph_is_current`); blocks `unverified`/`stale-graph`, **not** `stale-wiki` | Consistent with M3: a stale/absent wiki must never block a safety decision |
| D3 | Tier-B = `assess_impact` (always) + `explain_with_sources(require_verification=True)`; all others Tier-A (warn) | Smallest high-risk set; opt-in verification for explanations |
| D4 | **Record `graph_commit = repo_head`** in `build_and_save`/refresh | Closes the latent gap so `graph_is_current`/`assess_impact` actually pass when current |
| D5 | Bounded refresh: re-index CBM + rebuild entity_map; **no LLM wiki-regen** | Restores graph-freshness deterministically without LLM cost/risk |
| D6 | Refresh trigger = **manual/explicit**: MCP `refresh_index` tool (→ 12) + CLI/function | Predictable; agent can self-heal; no heavy work inside routine requests |
| D7 | `AppState` gains `repo_path` | Re-indexing CBM needs the repo path |

## 3. Components

```
repo_memory/
├── grounding.py        # + compute_freshness(state, *, entries_stale=False); require_fresh(state)
├── entity_map_build.py # build_and_save records graph_commit = repo_head (D4 fix)
├── graph/forward.py    # + index_repository(client, *, path) wrapper
├── refresh.py          # NEW: async refresh(state) -> envelope (re-index + rebuild + reload)
├── state.py            # AppState gains repo_path; load_app_state/server pass it
├── tools/wiki_tools.py # set freshness via compute_freshness
├── tools/bridge_tools.py # set freshness via compute_freshness(entries_stale=...)
├── tools/graph_tools.py  # set freshness via compute_freshness
├── tools/hybrid_tools.py # assess_impact -> require_fresh; explain_with_sources(require_verification)
└── server.py           # register refresh_index (→ 12 tools); pass repo_path
```

## 4. `compute_freshness` (D1)

```
compute_freshness(state, *, entries_stale=False) -> str:
  rh = state.repo_head; em = state.entity_map
  if state.cbm is None or not rh or em is None or not em.graph_commit: return "unverified"
  if em.graph_commit != rh or entries_stale:                          return "stale-graph"
  wiki_commit = (state.wiki.wiki_commit if state.wiki else em.wiki_commit)
  if wiki_commit and wiki_commit != rh:                                return "stale-wiki"
  return "fresh"
```
`entries_stale` lets a tool that ran verify-on-access (e.g. `get_related_files`) report drift as
`stale-graph`. This is the **reporting** enum used in every envelope's `freshness` field.

## 5. `require_fresh` + Two-Tier Policy (D2, D3)

```
require_fresh(state) -> dict | None:
  if graph_is_current(state): return None
  f = compute_freshness(state)   # "unverified" or "stale-graph"
  return envelope(None, freshness=f,
                  warnings=[f"verification required but graph is {f} (run refresh_index)"],
                  provenance=provenance(state))
```
- **Tier-A** (read-only): `get_repo_overview`, `list_modules`, `search_wiki`, `get_module_doc`,
  `get_related_files`, `search_code_graph`, `trace_symbol`, `get_code_snippet`, `get_architecture`,
  `explain_with_sources` (default) — set `freshness` via `compute_freshness`; **never block**.
- **Tier-B** (fail-closed): `assess_impact` (replaces its inline gate with `require_fresh`, keeping
  its extra blocks: `detect_changes` failure, symbol unverifiable); `explain_with_sources` when
  `require_verification=True` (calls `require_fresh` first). `require_fresh` is **graph-only** —
  `stale-wiki` never blocks.

## 6. `graph_commit` Recording Fix (D4)

`build_and_save(wiki, client, out_path, *, repo_root=None, repo_head=None)` passes
`graph_commit=repo_head` into `build_entity_map` (the graph was just enumerated at `repo_head`).
Result: a freshly built/refreshed entity_map has `graph_commit == repo_head` → `graph_is_current`
True → `assess_impact` and `require_fresh` pass when current. (Confirmed gap: today it's omitted →
`None` → always blocks.) Note: `graph_commit=repo_head` is correct on the assumption the caller
indexed CBM at `repo_head` before building — `refresh` (§7) guarantees this by re-indexing first;
the offline initial build likewise expects CBM indexed at the current checkout.

## 7. Bounded Refresh (D5, D6)

`graph/forward.py`: `async index_repository(client, *, path)` → CBM `index_repository`.

`refresh.py`:
```
async refresh(state) -> dict:
  if state.cbm is None: return envelope(None, warnings=["CBM unavailable"], provenance=...)
  await forward.index_repository(state.cbm, path=state.repo_path)          # re-index at HEAD
  em = await build_and_save(state.wiki, state.cbm, state.entity_map_path,
                            repo_head=state.repo_head)                      # rebuild, graph_commit=HEAD
  state.entity_map = em
  return envelope({"reindexed": True, "graph_commit": em.graph_commit,
                   "modules": len(em.modules)},
                  freshness=compute_freshness(state), provenance=provenance(state))
```
Exposed as MCP tool `refresh_index` (async, no args) and importable for CLI use. No wiki-regen.

## 8. `AppState.repo_path` + Server (D7)

`AppState` gains `repo_path: Optional[str] = None`. `load_app_state` and `build_app` accept and
thread it (server `main()` derives it, e.g. from cwd / env `REPO_MEMORY_REPO_PATH`). `server.py`
registers the 12th tool `refresh_index` with a routing-aware description ("re-index the code graph
and rebuild the map to restore freshness; call this when a tool reports stale-graph or blocks").

## 9. Expected Refactor Churn

Centralizing freshness changes some currently-asserted values. M2/M3 tool tests that expect
`"fresh"` use fixtures where `graph_commit != repo_head`; those fixtures are updated to align
`graph_commit == repo_head` (they were under-specified before). Scope: `test_rm_bridge_tools.py`,
`test_rm_hybrid_explain.py`, `test_rm_hybrid_impact.py` fixtures. Low-risk, mechanical.

## 10. Testing

- **Unit (offline):**
  - `compute_freshness`: full precedence table (unverified / stale-graph / stale-wiki / fresh; graph
    beats wiki; `entries_stale` → stale-graph).
  - `require_fresh`: returns None when graph-current; blocks on `unverified`/`stale-graph`; **does
    NOT block on `stale-wiki`** (wiki behind code, graph current → None).
  - `build_and_save` now records `graph_commit == repo_head` (mocked CBM).
  - Tier-A tools report `compute_freshness`-derived values; `explain_with_sources(require_verification=True)`
    returns a blocked envelope when stale-graph.
  - `assess_impact` still blocks via `require_fresh` (graph stale/CBM down) and its own conditions.
  - `refresh`: re-indexes (mocked), rebuilds, sets `graph_commit=repo_head`, flips freshness to fresh.
  - server: 12 tools registered with descriptions.
- **Integration (gated):** real `refresh` (uvx CBM) then `assess_impact` succeeds on a current graph.
- **Regression:** full offline suite green (note the pre-existing capture-teardown quirk; use `-s`).

## 11. Internal Phases (of the M4 plan)

- **(a)** `grounding.compute_freshness` + `require_fresh`.
- **(b)** `build_and_save` records `graph_commit = repo_head` (+ update entity_map_build test).
- **(c)** refactor Tier-A tools (wiki/bridge/graph) to `compute_freshness` (+ fixture churn).
- **(d)** `assess_impact` → `require_fresh`; `explain_with_sources` `require_verification`.
- **(e)** `forward.index_repository` + `refresh.py` + `AppState.repo_path`.
- **(f)** server `refresh_index` (→ 12) + integration test + offline gate.

## 12. Non-Goals (deferred)

LLM wiki-regeneration orchestration; routing eval harness + server-side classifier; agent-utility
evaluation. (These remain for a later milestone.)

## 13. Open Questions / Risks

- **`index_repository` real arg shape:** confirm CBM's argument (`path`?) and whether it re-indexes
  incrementally — resolve in phase (e)/integration, like `detect_changes` in M3.
- **`repo_path` source:** server `main()` default (cwd vs env) — pick env `REPO_MEMORY_REPO_PATH`
  with cwd fallback.
- **`wiki_commit` source for `compute_freshness`:** prefer `state.wiki.wiki_commit`, fall back to
  `entity_map.wiki_commit`; both come from codewiki `metadata.commit_id` (populated since M1).

### Related
- Parent: `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md`
- Builds on M2/M3: `...-m2-facade-design.md`, `...-m3-hybrid-design.md`
