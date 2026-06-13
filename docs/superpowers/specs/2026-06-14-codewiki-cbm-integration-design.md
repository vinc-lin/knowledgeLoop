# Design Spec: CodeWiki × Codebase-Memory-MCP Integration (`repo_memory`)

- **Date:** 2026-06-14
- **Product:** knowledgeLoop (umbrella). This spec makes this repo the **merge vehicle**.
- **New package:** `repo_memory/` — a unified Python MCP server.
- **Status:** Draft for user review (design direction approved).

---

## 1. Context & Motivation

An AI coding agent understanding a repository has two distinct needs:

- A **narrative map** — overall design, module boundaries, workflows. CodeWiki (`codewiki`)
  generates this as Markdown + Mermaid + a module tree.
- **Source-code evidence** — exact files, symbols, call chains, impact. Codebase-Memory-MCP
  (CBM) provides this as a queryable SQLite knowledge graph behind an MCP server.

These are complementary, not interchangeable. Reading source directly is token-expensive and
easy to get lost in; reading only the Wiki is imprecise and **can be wrong** — CodeWiki output
has measurable drift/hallucination (invented acronyms, stale counts, fabricated names, observed
in an audit of generated wikis). The integration's reason to exist is to let the
agent move from Wiki-level understanding to **graph-verified evidence**, and to surface drift
where the two disagree.

**Two facts (verified this session) shape the design:**

1. **CBM is already a complete MCP server.** It exposes `search_graph`, `query_graph` (Cypher),
   `trace_path`, `get_code_snippet`, `get_graph_schema`, `get_architecture`, `search_code`,
   `detect_changes`, `index_status`, `manage_adr`, etc. We **reuse**, not reimplement.
2. **The Wiki↔Graph mapping data already exists.** `module_tree.json` keys each module to
   components shaped as `path/to/file.py::SymbolName`; CBM nodes carry `file_path` + `name` +
   `qualified_name` + line span. The "bridge" is therefore largely a **deterministic join**, not
   a new retrieval/embedding system.

## 2. Goals / Non-Goals

**Goals**
- One Python MCP server (`repo_memory`) that is the agent's **sole endpoint**.
- A Wiki↔Graph **entity-map** (precomputed + verified-on-access) that grounds Wiki modules in
  real CBM nodes and exposes unmatched/drifted entries.
- A unified toolset (Wiki + bridge + forwarded-graph + hybrid) under a **single response
  contract**.
- A **two-tier freshness/verification policy**: warn for read-only, fail-closed for high-risk.
- A refresh path that keeps Wiki, graph, and repo HEAD aligned via `commit_id` provenance.

**Non-Goals (YAGNI for v1)**
- No server-side ML router/classifier initially (light routing; escalate only on eval evidence).
- No reranker initially.
- No reimplementation of any CBM capability.
- No modification of CBM's C source (consumed as an external binary).
- Not solving CodeWiki's hallucination at generation time here — we *expose* drift, not fix it.

## 3. Key Decisions (with rationale)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Unified facade** — one server; CBM spawned as an internal stdio MCP client; graph tools forwarded | Single clean toolset for the agent; reuse CBM wholesale |
| D2 | **Hybrid entity-map** — precomputed `entity_map.json` + cheap verify-on-access | Fast & inspectable, yet catches drift at the point of use |
| D3 | **Merge vehicle now** — `repo_memory/` ships beside `codewiki/` in this repo; product = knowledgeLoop | User intends to converge; CBM stays an external binary dep |
| D4 | **Light router** — LLM routes via strong tool descriptions; 2 server-side fusion tools | In MCP the calling LLM is the router; add a classifier only if routing evals show frequent errors |
| D5 | **Two-tier verification** — warn (read-only) vs fail-closed (high-risk) | Soft warnings are unsafe to act on for modification/impact/refactor |
| D6 | **Unified response contract** on every tool | Predictable freshness/provenance/confidence/warnings/unmatched for the agent |

## 4. Architecture & Package Layout

`codewiki/` keeps its name (standing CLAUDE.md rule). CBM is declared as an external binary
dependency and launched over stdio (e.g. `npx`/`uvx codebase-memory-mcp`, or an installed binary).

```
codewiki/            # (existing) doc generator — one additive change (see M1 / §9)
repo_memory/         # NEW unified MCP server
├── wiki/            # load + index codewiki artifacts (module_tree.json, metadata.json, *.md)
│   ├── loader.py        # parse module_tree.json → modules, components, children, paths
│   └── search.py        # lightweight wiki text/heading index
├── graph/            # CBM client
│   ├── client.py        # stdio MCP client (spawn + JSON-RPC), lifecycle, health
│   └── forward.py       # thin pass-through wrappers; declared CBM tool surface it tracks
├── bridge/           # KEYSTONE
│   ├── builder.py       # deterministic join → entity_map.json
│   ├── verify.py        # verify-on-access existence/line checks + live re-resolve
│   └── schema.py        # EntityMap / EntityEntry dataclasses
├── contract.py       # the unified response envelope (§6)
├── tools/            # MCP tool definitions, grouped (wiki / bridge / forwarded / hybrid)
├── router.py         # light routing helpers + the 2 fusion flows (§7)
├── refresh.py        # commit_id alignment + incremental rebuild (§8)
└── server.py         # the unified MCP facade (sole agent endpoint)
```

## 5. The Bridge / Entity-Map (keystone)

**Inputs**
- Source A — `module_tree.json`: `{ module: { path, components: ["file::Symbol", …], children } }`.
- Source B — CBM graph nodes: `{ id, label, name, qualified_name, file_path, start_line, end_line }`.

**Build (`bridge/builder.py`)** — a layered join per component:
1. Normalize Wiki paths to repo-relative; split `file::Symbol`.
2. Match against CBM nodes: (a) exact `(file_path, name)`; else (b) `qualified_name` suffix; else
   (c) file-only (symbol unresolved); else (d) **unmatched**.
3. Record per entry: `cbm_node_id`, `file`, `lines`, `match_strategy`, `confidence`
   (exact=1.0, qualified-suffix≈0.85, file-only≈0.5).

**Artifact — `entity_map.json`** (inspectable, committed-or-cached):
```json
{
  "built_at_repo_head": "<sha>",
  "wiki_commit": "<sha|null>",
  "graph_commit": "<sha|null>",
  "modules": [{
    "module": "ingestion",
    "wiki_page": "docs/ingestion.md",
    "path": "src/ingest",
    "entries": [{
      "symbol": "IngestionPipeline", "file": "src/ingest/pipeline.py",
      "cbm_node_id": "…", "lines": [10, 88],
      "match_strategy": "exact", "confidence": 1.0
    }],
    "unmatched": [{ "symbol": "chunkDocument", "file": "src/ingest/chunker.py",
                    "reason": "no_cbm_node" }]
  }]
}
```
`unmatched` is first-class output — it is precisely where the Wiki drifted from code.

**Verify-on-access (`bridge/verify.py`)** — always-on, cheap. When a tool returns bridge entries,
re-check just those `cbm_node_id`s exist with matching file/line via CBM; on miss, mark the entry
`stale` and attempt a single live re-resolve. Feeds the `freshness` field of the response.

## 6. Unified Response Contract

**Every** tool returns this envelope (`contract.py`):
```json
{
  "result": { /* tool-specific payload */ },
  "freshness": "fresh | stale-wiki | stale-graph | unverified",
  "provenance": { "repo_head": "<sha>", "wiki_commit": "<sha|null>", "graph_commit": "<sha|null>" },
  "confidence": 0.0,            // bridge/hybrid grounding strength; null when N/A
  "warnings": ["…"],
  "unmatched": [ /* EntityEntry[] that could not be grounded for this response */ ]
}
```
- `freshness` is computed from verify-on-access + the three commit ids in `provenance`:
  - `fresh` — `wiki_commit == graph_commit == repo_head` and verify-on-access passed for returned entries.
  - `stale-wiki` — `wiki_commit != repo_head` (docs behind code).
  - `stale-graph` — `graph_commit != repo_head` (graph behind code).
  - `unverified` — verify-on-access could not run (CBM unavailable) or there were no backing entries to verify.
- `confidence` aggregates entity-map match confidence for the entries backing the answer.
- `unmatched` lets the agent see exactly what could not be grounded.

## 7. Tools & Routing

Unified toolset = forwarded CBM tools (pass-through) + new Wiki/bridge/hybrid tools. Every tool's
description encodes the routing table so the LLM can self-route.

| Tool | Tier | Source | Notes |
|------|------|--------|-------|
| `get_repo_overview` | A read-only | wiki | overview.md + metadata |
| `list_modules` | A | wiki | module_tree.json |
| `search_wiki` | A | wiki | text/heading index |
| `get_module_doc` | A | wiki | one module's doc + its entity entries |
| `get_related_files` | A | bridge | module/topic → files + symbols + cbm_node_ids |
| `search_code_graph` | A | forward→`search_graph` | |
| `trace_symbol` | A | forward→`trace_path` | |
| `get_code_snippet` | A | forward→`get_code_snippet` | |
| `get_architecture`, `detect_changes`, `search_code` | A | forward (as-is) | |
| `explain_with_sources` | A or **B** | hybrid | `require_verification` flag flips it to Tier B |
| `assess_impact` | **B high-risk** | hybrid | trace + detect_changes + entity-map; **fail-closed** |

**Routing (D4):** no ML classifier in v1. Intelligence lives in (a) tool descriptions encoding
"architecture/responsibility → wiki; location/call-chain/impact → graph; explanation-with-evidence
→ hybrid", and (b) the two server-side fusion tools. `router.py` only orchestrates the fusion
fan-out. **Escalation trigger:** add a server-side classifier only if routing evals (M5) show
frequent tool-selection errors.

**Fusion flow — `explain_with_sources("how does chunking work?")`:**
`search_wiki` → top module/section → entity-map entries → verify-on-access against CBM →
`get_code_snippet`/`trace_path` for evidence → return Wiki narrative + graph-verified evidence
wrapped in the §6 contract.

## 8. Freshness, Verification Policy & Refresh

**Provenance (three commit ids):**
- `repo_head` — server reads it directly via git.
- `wiki_commit` — from `metadata.json.commit_id` (**requires the M1 codewiki fix**, see §9).
- `graph_commit` — from CBM `index_status`; if CBM does not report it, `refresh.py` records the
  commit it indexed at in a sidecar file.

**Two-tier policy (D5):**
- **Tier A (read-only / explanatory):** serve-with-warning. If `freshness != fresh`, return the
  answer with a `warnings` entry; never block.
- **Tier B (high-risk: modification, impact analysis, refactoring):** **fail-closed.** The tool
  must fully ground every claim against a current graph. If CBM is unreachable, `graph_commit !=
  repo_head`, or any backing entry is `stale`/`unmatched`, the tool returns a blocked status
  (not a soft warning), telling the agent to refresh/index first. Tool descriptions instruct
  agents to use Tier-B tools (or `explain_with_sources(require_verification=true)`) for these tasks.

**Refresh (`refresh.py`):** on new commits — incremental CBM re-index → regenerate affected Wiki
modules → rebuild entity-map → mark unrebuilt sections stale. Goal alignment:
`wiki_commit == graph_commit == repo_head`.

## 9. Dependencies on `codewiki` (in-scope changes)

- **Populate `metadata.commit_id`** at generation time. It is currently written as `null`; all
  freshness checks depend on it. This is the only required codewiki change and lands in **M1**.
- (Optional, later) emit a machine-stable per-module → components artifact if `module_tree.json`
  parsing proves brittle — not needed for v1.

## 10. Error Handling / Graceful Degradation

- CBM client down/crashed → Tier A degrades to **wiki-only + warning**; Tier B **blocks**.
- Wiki artifacts missing → **graph-only** (forwarded tools still work); wiki/bridge tools warn.
- Entity-map miss for a query → fall back to **live resolution** for that query (lazy path).
- CBM client lifecycle: spawn on server start, health-check, auto-restart with backoff.

## 11. Testing Strategy

- **Unit:** `bridge/builder.py` join — path normalization, the four match strategies, confidence,
  and `unmatched` capture — on fixtures.
- **Real corpora:** we already have generated wikis for **this repo (knowledgeLoop)** *and*
  **codebase-memory-mcp**. Use both as integration fixtures: build an entity-map against a real CBM
  `.db`, assert grounding rates and known drift (e.g. CBM's hallucinated acronyms surface as
  `unmatched`/low-confidence).
- **Contract tests:** every tool returns a valid §6 envelope; Tier-B fail-closed paths assert
  *blocked* (not warned) when the graph is stale/absent.
- **Routing golden tests:** representative questions → expected tool; this set also seeds the M5
  routing eval that gates D4 escalation.

## 12. Milestones (phases within this one spec)

- **M0 — Merge reframing:** umbrella naming/packaging; `repo_memory/` scaffold; CBM declared as a
  dependency. Keep `codewiki` name.
- **M1 — Bridge keystone:** `entity_map` builder + verify-on-access + `entity_map.json`; **codewiki
  `metadata.commit_id` fix**. Standalone-testable.
- **M2 — Facade server:** `server.py` + CBM stdio client + forwarded graph tools + Wiki tools, all
  under the §6 contract.
- **M3 — Hybrid + routing:** `explain_with_sources`, `assess_impact`, description-based routing.
- **M4 — Freshness & policy:** provenance/three-commit checks, two-tier verification, `refresh.py`,
  degradation paths.
- **M5 — Extras (deferred/optional):** routing eval harness (gates D4), reranker, agent-utility
  evaluation.

## 13. Open Questions / Risks

- **Path normalization** between CodeWiki repo-relative paths and CBM `file_path` (absolute vs
  relative) — resolve empirically in M1 against the real corpora.
- **`graph_commit` exposure** — confirm whether CBM `index_status` reports the indexed commit; if
  not, rely on the `refresh.py` sidecar.
- **CBM tool-surface drift** — the forwarding layer (`graph/forward.py`) must track CBM's tool
  schema across CBM versions; pin a tested CBM version and smoke-test on upgrade.
- **Module-tree brittleness** — `module_tree.json` is the join's Source A; canonicalization changes
  in codewiki could alter shapes (see `docs/superpowers/specs/2026-06-14-canonical-doc-filenames-design.md`).

---

### Related docs
- `docs/findings-and-practices.md` — CodeWiki operational learnings (incl. why generated docs
  drift), which motivates the graph-verification keystone.
- `docs/superpowers/specs/2026-06-14-canonical-doc-filenames-design.md` — doc-naming changes that
  affect `module_tree.json` shapes (the bridge's Source A).
