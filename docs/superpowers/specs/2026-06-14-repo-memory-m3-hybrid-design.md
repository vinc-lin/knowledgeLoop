# Design Spec: repo_memory M3 — Hybrid Fusion Layer

- **Date:** 2026-06-14
- **Parent spec:** `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md` (M0–M5)
- **Builds on:** M0–M2 (branch `feat/repo-memory-m0-m1`) — the bridge keystone + the unified
  facade (graph client, forwarded tools, node source + `CBMGraphProbe`, manifest-anchored wiki,
  entity_map build, response contract, `AppState`, wiki/bridge/graph tool logic, FastMCP server).
- **Status:** Draft for user review (design approved with adjustments).

---

## 1. Context & Scope

M2 shipped the unified facade with read-only wiki tools, `get_related_files` (precomputed map +
verify-on-access), and forwarded graph tools. M3 adds the **hybrid fusion layer** — two tools that
*combine* the wiki narrative with graph-verified evidence:

- **`explain_with_sources`** — read-only: a wiki explanation **backed by graph-grounded source
  evidence** (the project's core value: narrative + proof).
- **`assess_impact`** — **fail-closed** change-impact analysis: blocks unless it can ground the
  blast radius in a *current* graph.

In scope: both tools + description-based routing for them. **Out of scope (M4/M5):** the general
two-tier verification policy across all tools, the full `freshness` enum, automated entity_map /
index refresh, and any server-side routing classifier.

## 2. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| S1 | Deliver **both** hybrid tools in M3; `assess_impact` is **fail-closed now** | Completes the fusion layer cohesively; fail-closed is feasible on M2 primitives (verify-on-access + recorded `graph_commit`) |
| S2 | `explain_with_sources` returns **multiple** grounded symbols/snippets, each tagged with its **grounding method**, and surfaces **unmatched** | One symbol is too thin; the agent needs several evidence points + provenance of how each was grounded |
| S3 | `assess_impact` fail-closed gate is **graph-grounding only** | Safety depends on verifying the blast radius in the real graph, not on wiki coverage |
| S4 | A missing **wiki module mapping never blocks** `assess_impact` → `module=null` + warning | Wiki enrichment is best-effort; it must not gate a safety decision |
| S5 | `detect_changes` stays **internal-only**; `assess_impact` is the public Tier-B tool | `assess_impact` adds freshness, graph verification, provenance, and the fail-closed policy |
| S6 | Routing = **descriptions only** (no classifier) | Classifier deferred to M5 pending routing evals |
| S7 | Doc-name↔module-name is **best-effort** for M3; explicit `wiki_page → module_id` deferred | Acceptable fallback now; a real mapping is a tracked follow-up |

## 3. Components (extend M2)

```
repo_memory/
├── graph/forward.py        # + detect_changes(client, *, base_branch=None) wrapper
├── grounding.py            # NEW: graph_is_current(state) + helpers for the fail-closed gate
├── tools/hybrid_tools.py   # NEW: explain_with_sources, assess_impact (logic fns -> envelope)
└── server.py               # register the 2 new tools -> 11 tools, with routing-aware descriptions
```

`grounding.py` reuses M2 primitives (the recorded `graph_commit`, `repo_head`, verify-on-access via
`CBMGraphProbe`). `hybrid_tools.py` composes existing M2 tool functions; no graph/wiki logic is
reimplemented.

## 4. `explain_with_sources(state, query)` — read-only fusion

Returns the §6 envelope. Steps:
1. `search_wiki(query)` → top doc hit = the **narrative**.
2. **Grounding (S2, S7):**
   - Resolve the doc to a module (best-effort doc-name ↔ module-name). If resolved →
     `get_related_files(module)` for entity-map-grounded entries (`grounding_method="entity_map"`).
   - **Fallback** (no module match): `search_code_graph` by query-derived terms, adapt hits
     (`grounding_method="graph_search"`).
3. Take the **top N grounded symbols** (default N=3), fetch a `get_code_snippet` for each as
   concrete evidence (verify-on-access applied).
4. **Result:**
   ```
   { "narrative": <wiki excerpt>, "module": <name|null>,
     "evidence": [ { "symbol", "file", "lines", "snippet", "grounding_method",
                     "confidence", "stale" }, ... up to N ] }
   ```
   plus envelope `confidence` (aggregate), `unmatched` (entity-map misses surfaced), `freshness`,
   `provenance`, `warnings`.
- **Degradation:** CBM down → narrative only + warning (no evidence); no wiki → graph-only evidence
  with a warning. Never blocks (read-only).

## 5. `assess_impact(state, base_branch=None)` — Tier-B, fail-closed

**Fail-closed gate (graph-grounding only — S3, S4).** Return a **blocked** envelope
(`result=None`, `warnings=[...]`, appropriate `freshness`) when ANY of:
1. **CBM unavailable** (`state.cbm is None` or client down).
2. **Graph stale** — `graph_commit != repo_head`.
3. **Base branch unresolved** — `base_branch` (or the inferred default) does not resolve.
4. **Unsupported worktree state** — git state `detect_changes` cannot handle.
5. **`detect_changes` fails** (CBM error).
6. **An impacted symbol cannot be verified** in the current graph (verify-on-access: absent/moved).

A missing **wiki** module mapping is **NOT** a block condition (S4) — see below.

**Happy path** (gate passes):
1. `detect_changes(base_branch)` → impacted symbols + blast radius + risk (CBM provides these).
2. Verify each impacted symbol against the current graph (`CBMGraphProbe` + `verify_entries`); if
   any is unverifiable → **block** (condition 6).
3. **Enrich (best-effort, never blocks):** map each impacted symbol to its entity-map module for
   wiki context; if none, set `module=null` and add a warning listing those symbols.
   Optionally add `trace_path` callers per impacted symbol.
4. **Result:**
   ```
   { "base_branch": <resolved>, "changes": [<files>],
     "impacted": [ { "symbol", "file", "risk", "module"|null, "callers", "verified": true }, ... ],
     "blast_radius": <n> }
   ```
   envelope `freshness="fresh"`, `confidence`, `provenance`, `warnings` (e.g. symbols lacking a
   wiki module). Blocked responses set `result=None` with an actionable warning
   ("re-index: graph not current", "base branch X unresolved", etc.).

## 6. Response Contract

Both tools return the parent spec's §6 envelope (reusing `contract.envelope`). M3 sets `freshness`
conservatively (`fresh` only when graph-current and verify passed; `stale-graph`/`unverified`
otherwise) — the full enum logic remains M4.

## 7. Routing (S6)

No classifier. The two new tools carry routing-aware descriptions:
- `explain_with_sources`: "Explain how something works **with graph-verified source evidence** —
  use for 'how does X work / why' questions that need proof, not just narrative."
- `assess_impact`: "Assess the blast radius of current changes (**fail-closed**, graph-verified) —
  use before modifying/refactoring or for 'what does this change affect' questions."

## 8. Error Handling / Degradation

- `explain_with_sources` (read-only): degrades to narrative-only or graph-only with warnings; never blocks.
- `assess_impact` (Tier-B): **fail-closed** per §5 — degradation is *blocking with an actionable
  warning*, never a partial/optimistic impact set.
- Both reuse M2's CBM client resilience (`call_tool_with_restart`) and `provenance`.

## 9. Testing (corpus = knowledgeLoop, wiki = generated docs)

- **Unit (offline, mocked `state`/CBM client):**
  - `explain_with_sources`: entity-map path returns N grounded snippets with
    `grounding_method="entity_map"`; fallback path uses `graph_search`; unmatched surfaced;
    CBM-down → narrative-only + warning; no-wiki → graph-only.
  - `assess_impact`: each of the 6 block conditions returns a blocked envelope; the happy path
    returns the impact set; a symbol with no wiki module → `module=null` + warning (NOT blocked).
  - `detect_changes` wrapper maps to the right CBM tool + args.
- **Integration (gated `@pytest.mark.integration`):** real `assess_impact` against the corpus
  (index, make a change, assert grounded blast radius); confirm a stale-graph state blocks.

## 10. Internal Phases (of the M3 plan)

- **(a)** `graph/forward.py` `detect_changes` wrapper.
- **(b)** `grounding.py` `graph_is_current` + gate helpers.
- **(c)** `tools/hybrid_tools.py` `explain_with_sources`.
- **(d)** `tools/hybrid_tools.py` `assess_impact` (gate + happy path + enrichment).
- **(e)** `server.py` register the 2 tools (→ 11) with descriptions; integration test + gate.

## 11. Non-Goals (deferred)

General two-tier verification policy across ALL tools, full `freshness` enum, automated
entity_map/index refresh (**M4**); server-side routing classifier + routing eval harness (**M5**);
explicit `wiki_page → module_id` mapping (tracked follow-up, S7).

## 12. Open Questions / Risks

- **`detect_changes` real shape:** confirm its argument for the diff base (`base_branch`?) and how
  it signals an unresolved base / unsupported worktree (block conditions 3–4) — resolve in phase (a)
  against real CBM; until then, model conditions 3–4 via `detect_changes` error + a small git
  pre-check.
- **Doc↔module resolution** (S7): best-effort name match may miss canonicalized doc names; the
  graph-search fallback covers misses for `explain_with_sources`.
- **`base_branch` default:** when omitted, decide the inferred base (e.g. merge-base with the
  default branch) vs. uncommitted-only diff — confirm against `detect_changes` behavior.

### Related
- Parent: `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md`
- Builds on: `docs/superpowers/specs/2026-06-14-repo-memory-m2-facade-design.md`
