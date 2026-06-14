# Design Spec: repo_memory M2 — Unified MCP Facade (MVP)

- **Date:** 2026-06-14
- **Parent spec:** `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md` (M0–M5)
- **Builds on:** M0+M1 (branch `feat/repo-memory-m0-m1`) — the `repo_memory/bridge/` keystone
  (`build_entity_map`, `verify_entries` + `GraphProbe`, `schema.NodeRecord/EntityEntry/...`).
- **Status:** Draft for user review (design approved).

---

## 1. Context & Scope

M1 produced a **pure, offline** Wiki↔Graph bridge library (no I/O, no CBM). M2 turns it into a
**running MCP server an agent can call** — the unified facade. M2 is an **MVP**: expose basic
Wiki tools, forward a *selected* set of CBM graph tools, and serve `get_related_files` from the
**precomputed** `entity_map.json`. It deliberately does **not** build a heavy router, a reranker,
or a hybrid reasoning system (those are M3/M4).

The four engineering requirements that define "done" for M2 (acceptance criteria in §13):
**stable CBM process management, a unified tool response contract, clear tool descriptions
(light/LLM-driven routing), and graceful degradation** when either the Wiki artifacts or CBM are
unavailable.

## 2. Locked Decisions

| # | Decision | Choice |
|---|----------|--------|
| T | Transport | Official `mcp` Python SDK — stdio **client** to CBM + the SDK **server** framework for our facade (already installed in the venv) |
| L | CBM launch | Spawn `uvx codebase-memory-mcp` (pinned v0.7.0); spawn command **configurable** |
| E | Node enumeration | **Per-module** via `search_graph` with file-pattern scoping + pagination → `NodeRecord`s |
| P | `graph_commit` provenance | Recorded by us at index time (CBM `index_status` returns counts only, not the commit). Full freshness enum = M4 |
| C | Corpus / wiki | knowledgeLoop code (CBM-indexed) ↔ **codewiki-generated docs**; wiki loader **anchored on the generation manifest** (`module_tree.json` + `metadata.json`) |
| N | Node identity | `NodeRecord.node_id = qualified_name` (CBM addresses nodes by QN, not an opaque id) → **M1 bridge reused unchanged**; `GraphProbe.lookup(qn)` resolves via CBM |

## 3. Architecture & Components

New code under `repo_memory/` (M1 `bridge/` reused as-is):

```
repo_memory/
├── graph/
│   ├── client.py     # mcp-SDK stdio client: spawn uvx CBM, initialize, call_tool, lifecycle
│   ├── forward.py    # thin pass-through wrappers for the selected CBM tools (§4)
│   └── nodes.py      # enumerate_nodes_for_files() -> NodeRecord[]; concrete GraphProbe
├── wiki/
│   ├── loader.py     # manifest-anchored load of codewiki-generated docs (§5)
│   └── search.py     # light heading/text index over generated module docs
├── contract.py       # the unified response envelope (§6)
├── entity_map_build.py  # offline build step: enumerate + build_entity_map -> entity_map.json
├── tools/            # MCP tool definitions (wiki / bridge / forwarded), each contract-wrapped
└── server.py         # the facade MCP server: wires client + wiki + bridge + tools; owns CBM lifecycle
```

Each file has one responsibility; `graph/forward.py` is the single place that knows CBM's tool
schema (so drift is contained).

## 4. Agent-Facing Toolset (9) — deliberately small

| Tool | Kind | Backed by |
|------|------|-----------|
| `get_repo_overview` | Wiki | `overview.md` + `metadata.json` |
| `list_modules` | Wiki | `module_tree.json` |
| `search_wiki` | Wiki | `wiki/search.py` index |
| `get_module_doc` | Wiki | a module's generated `*.md` + its entity-map entries |
| `get_related_files` | Bridge | **precomputed `entity_map.json`** + verify-on-access |
| `search_code_graph` | Forwarded | CBM `search_graph` |
| `trace_symbol` | Forwarded | CBM `trace_path` |
| `get_code_snippet` | Forwarded | CBM `get_code_snippet` |
| `get_architecture` | Forwarded | CBM `get_architecture` |

**Internal-only (used by the facade, not exposed):** `search_graph` (node enumeration),
`get_graph_schema`, `index_status`, `list_projects`.

**Excluded from the MVP surface:** `query_graph` (raw Cypher), `detect_changes` (→ M3/M4
high-risk flows), `delete_project`, `index_repository`, `manage_adr`, `ingest_traces`.

All 9 entries above (incl. `get_architecture`) return the §6 envelope.

## 5. Wiki Loading (manifest-anchored) & Entity-Map Build vs. Serve

**Manifest-anchored loading:** `wiki/loader.py` reads `module_tree.json` and `metadata.json`
(using its `files_generated` list and `commit_id`) and loads **only** the codewiki-generated
`*.md`. It does **not** blind-scan the docs directory — this excludes non-generated material
(`docs/superpowers/**`, `findings-and-practices.md`, `_fixed/_v2` dupes). The wiki directory is a
**configurable path** (default: the repo's codewiki output dir).

**Build vs. serve (hybrid, per parent spec D2):**
- **Build (offline, `entity_map_build.py`):** for every module in `module_tree.json`, enumerate
  its files' nodes via `graph/nodes.py` → `build_entity_map(...)` → write `entity_map.json`
  (stamped with `wiki_commit` from metadata, `repo_head` from git, `graph_commit` recorded now).
- **Serve (request path):** `get_related_files` **reads** `entity_map.json` and runs
  verify-on-access (`verify_entries` + the concrete `GraphProbe`). No graph crawl in the request
  path. Automated rebuild/refresh of the artifact is **M4**.

## 6. Response Contract in M2

Every tool returns the parent spec's §6 envelope:
`{ result, freshness, provenance{repo_head, wiki_commit, graph_commit}, confidence, warnings[], unmatched[] }`.

M2 populates:
- `result` — tool-specific payload (wiki content, bridge entries, or forwarded CBM result).
- `provenance` — `repo_head` (git), `wiki_commit` (`metadata.json`), `graph_commit` (our build-time record; may be `null` if unknown).
- `confidence` / `unmatched` — from the bridge for `get_related_files`; `null`/`[]` for tools where N/A.
- `warnings` — degradation notices (§8).
- `freshness` — M2 sets `"unverified"` by default and `"fresh"` only when verify-on-access passes and the three commits agree; the **full enum logic lands in M4**, so M2 keeps it conservative.

## 7. CBM Process Management (requirement 1)

`graph/client.py` owns one long-lived CBM subprocess:
- Spawn the configured command (`uvx codebase-memory-mcp` default) and run the MCP `initialize` handshake on startup.
- `call_tool(name, args)` with a per-call **timeout**; serialize access so concurrent tool calls don't corrupt the stdio stream.
- **Health + auto-restart:** detect a dead/hung process and restart with **exponential backoff** (bounded); surface restart state to callers.
- Clean shutdown on server exit (terminate child, drain).

## 8. Graceful Degradation (requirement 4)

| Outage | Behavior |
|--------|----------|
| **CBM unavailable** (spawn fails / crash-looping) | Wiki tools answer normally **+ a `warnings` entry**; forwarded tools and bridge-verify return a clear **degraded** result (not an exception), `freshness="unverified"` |
| **Wiki artifacts missing/unreadable** | Forwarded CBM tools work normally; wiki + bridge tools return an explicit "wiki unavailable" warning |
| **`entity_map.json` missing** | `get_related_files` degrades to a warning (and, if CBM is up, may fall back to a single live per-file resolution) |

Nothing in M2 hard-blocks (Tier-B fail-closed is M3/M4).

## 9. Tool Descriptions / Light Routing (requirement 3)

No server-side classifier in M2. Each tool's MCP **description encodes when to use it** (the
parent spec's routing table: architecture/responsibility → wiki tools; location/call-chain →
graph tools; "which files/symbols implement this module" → `get_related_files`). The descriptions
are the routing mechanism. The eval that could justify a real classifier is **M5**.

## 10. Testing (corpus = knowledgeLoop, wiki = generated docs)

- **Unit (offline, default suite):**
  - `wiki/loader.py` is manifest-anchored — loads only `files_generated`, **excludes** `docs/superpowers/**` and `findings-and-practices.md` (fixture with a mixed dir).
  - `graph/nodes.py` adapter: a CBM `search_graph` result row → `NodeRecord` (with `node_id = qualified_name`), against canned CBM responses.
  - `graph/forward.py`: each wrapper calls the right CBM tool with the right args, against a **mocked** client.
  - `contract.py`: every tool's output validates against the envelope shape.
  - degradation: simulate CBM-down and wiki-missing (mocked) → correct warnings, no exceptions.
- **Integration (gated behind `@pytest.mark.integration`; needs network for `uvx` + a CBM run):**
  index knowledgeLoop with CBM, run the build step against `docs/module_tree.json`, assert real
  grounding (e.g. `Configuration`, `LLMBackend` resolve exactly) **and** that known codewiki drift
  surfaces as `unmatched`. Also: kill the CBM process mid-session and assert the client restarts.
  The default suite stays offline/fast.

## 11. Internal Phases of Plan 2

Each independently testable; ordered by dependency:
- **(a)** `graph/client.py` — CBM stdio client + lifecycle (req 1).
- **(b)** `graph/forward.py` — selected forwarded wrappers.
- **(c)** `graph/nodes.py` — node source + concrete `GraphProbe`.
- **(d)** `wiki/loader.py` + `wiki/search.py` — manifest-anchored wiki layer.
- **(e)** `entity_map_build.py` — offline build wiring (a+c+d).
- **(f)** `contract.py` + `tools/` + `server.py` — envelope, the 8 tools, the facade (req 2,3,4).

## 12. Non-Goals (deferred)

Heavy/server-side router, reranker, hybrid tools (`explain_with_sources`, `assess_impact`),
Tier-B fail-closed verification, the full `freshness` enum, and automated entity-map
refresh — all **M3/M4**. `query_graph`/`detect_changes` exposure — later if warranted.

## 13. Acceptance Criteria

1. **CBM process management:** client survives a CBM crash (auto-restart with backoff) and a
   hung/slow call (timeout); clean shutdown — covered by an integration test.
2. **Unified contract:** all 9 tools return a valid §6 envelope — contract test.
3. **Clear descriptions:** all 9 tools carry routing-aware descriptions (reviewed).
4. **Graceful degradation:** CBM-down and wiki-missing both degrade with warnings and no
   exceptions — covered by unit tests in both directions.
5. Real grounding demonstrated on knowledgeLoop (integration test): exact matches for known
   symbols + drift surfaced as `unmatched`.

## 14. Open Questions / Risks

- **`search_graph` result fields:** confirm results include `file_path` **and line spans**
  (`start_line`/`end_line`) needed for `NodeRecord`; if not, fall back to `query_graph` or
  `get_code_snippet` for line spans. Resolve empirically in phase (c).
- **File-pattern scoping semantics:** confirm `search_graph`'s file filter accepts the path form
  we pass (and pagination via limit/offset) — resolve in phase (c) against real CBM.
- **Path normalization at the real boundary:** CBM `file_path` (absolute? project-relative?) vs
  CodeWiki repo-relative — exercises M1's `normalize_path`/`path_suffix_match`; tune `repo_root`
  passed to `build_entity_map`.
- **uvx in CI/offline:** integration tests need network to fetch CBM; marker-gated so the default
  suite is unaffected.
- **CBM tool-surface drift:** pin v0.7.0; `graph/forward.py` smoke-tests the tool list on startup.

### Related
- Parent: `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md`
- Prior plan: `docs/superpowers/plans/2026-06-14-repo-memory-m0-m1-bridge.md`
