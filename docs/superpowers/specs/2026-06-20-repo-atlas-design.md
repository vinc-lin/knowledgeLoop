# repo_atlas — Cross-Repo Knowledge Base (Design Spec)

**Date:** 2026-06-20 · **Status:** Design (Phase 1) · **Name:** `repo_atlas` (provisional)

## 1. Summary

`repo_atlas` is a cross-repo layer that **fully exploits the knowledge KnowledgeLoop has
already produced** — across all registered repos — to help a coding agent (e.g. Claude
Code) **write functions and fix bugs**. It is **read-only** over existing artifacts: it
mines the per-repo wikis, code graphs, entity-map bridges, and freshness signals that
`codewiki` + `repo_memory` + CBM already generate, and serves them through a small set of
MCP tools.

It delivers two capabilities in one effort:

- **C — Cross-repo discovery:** `find_related(query)` returns a ranked, repo-tagged set of
  similar implementations, callable building blocks, usage, and conventions, fused from all
  existing signals.
- **A — Task-scoped grounding + guardrails:** `prepare_change(target)` assembles a grounded
  context pack for the change in front of you; `verify_grounding(code)` flags hallucinated
  APIs; `assess_impact` (reused from `repo_memory`) gives blast radius.

## 2. Principle & non-goals

**Principle: exploit before acquire.** Maximize value from already-produced knowledge before
investing in capturing new knowledge.

**Non-goals (explicitly deferred):**

- **The feedback loop (gaining new knowledge)** — writing execution outcomes/gotchas/decisions
  back into the KB. This is a later phase, not Phase 1.
- **Regenerating or improving the per-repo wikis/graphs.** `repo_atlas` consumes them as-is;
  producing them stays `codewiki` + CBM's job.
- **Replacing `repo_memory`.** `repo_atlas` sits above it and reuses it.
- **A standalone semantic search product.** The differentiator is grounding (every result
  traces to real, current artifacts) + fusing all four signals — not search alone.

## 3. What it exploits (the four existing signals)

For any query/task, `repo_atlas` draws on **every modality, across every registered repo**,
and **never invents** — a result ships only if it traces to a real artifact.

| Signal | Source (already produced) | Exploited for |
|---|---|---|
| **Wiki narrative** | CodeWiki module docs + overview (`repo_memory.wiki.loader`) | Conventions, the *why* |
| **Code graph** | CBM symbols/snippets/edges (`repo_memory.graph`) | Similar implementations, building blocks, usage |
| **Bridge** | `entity_map.json` module→files (`repo_memory.bridge.schema`) | Concept → exact files/symbols |
| **Freshness/provenance** | per-repo `repo_head`, commit alignment (`repo_memory.grounding`) | Trust: how current/grounded each hit is |

## 4. Architecture

A new `repo_atlas/` package, a sibling of `codewiki/` and `repo_memory/`, layered **above**
`repo_memory` (no restructure required — the lower `repo_memory` layers are leaf modules with
no coupling to its MCP server/state).

```
codewiki/      produce: wikis (8→9 langs)
repo_memory/   single-repo consume: wiki+graph+bridge loaders, CBM client, envelope, freshness
repo_atlas/    cross-repo exploit (NEW)
  ├─ registry.py   which repos + where their artifacts live
  ├─ index/        indexer: artifacts → unified store (CBM touched at INDEX time only)
  ├─ store.py      SQLite (FTS5 + embedding vectors), under $HOME (off v9fs)
  ├─ embed.py      Embedder → gateway /v1/embeddings (GPU-served)
  ├─ retrieve.py   hybrid keyword+semantic, RRF fusion, freshness-tagged
  ├─ tools.py      find_related / prepare_change / verify_grounding / list_repos
  └─ server.py     repo_atlas MCP server (stdio), separate from repo_memory
```

**Key scaling property:** at **query time**, `find_related` hits **only the SQLite store** —
no live CBM fan-out — which is what makes "starts small, grows to many repos" hold.
`prepare_change` may spin CBM for the **single** target repo on demand (bounded, not fan-out).

## 5. Data model & store

One SQLite file (default `~/.repo_atlas/atlas.db`, off the v9fs mount per the corpora rule).

- **`units`** — one row per retrievable unit:
  `id, repo, kind ('doc'|'symbol'), name, qualified_name, file, repo_head, content_hash, text, meta(json)`.
- **`units_fts`** — FTS5 virtual table over `text` (+ `name`, `qualified_name`) for BM25 keyword search.
- **`vectors`** — `unit_id, dim, embedding(blob)`. At Phase-1 scale (a few thousand units) we do
  brute-force cosine in Python; an ANN index can replace this later with **no schema change**.
- **`repos`** — registry snapshot: `repo, indexed_repo_head, indexed_at, unit_count`.

`content_hash` makes re-indexing idempotent (skip unchanged units).

## 6. Indexing pipeline (`repo_atlas index [--all | <repo>]`)

Per registered repo:

1. **Wiki units** — `repo_memory.wiki.loader.load_wiki(wiki_dir)`; split each module doc +
   overview by heading into `kind='doc'` units (carry module name + bridged files).
2. **Symbol units** — spawn CBM via `repo_memory.deploy.resolve_launch_spec` + `graph.client`,
   resolve the project, and **enumerate all symbols** (new `enumerate_all_nodes` helper, §10) →
   `kind='symbol'` units carrying `qualified_name`, signature, file, and source snippet.
3. **Embed** units in batches via the gateway (`embed.py`).
4. **Upsert** into the store, tagged with the repo's current `repo_head` + `content_hash`.

CBM is used **only here**, never at `find_related` time.

## 7. Retrieval & ranking

`find_related(query, repos=None, kinds=None, k=20)`:

1. Embed the query (gateway) → cosine over `vectors` → semantic top-N.
2. FTS5 BM25 over `units_fts` → keyword top-N.
3. Fuse the two ranked lists with **Reciprocal Rank Fusion** (RRF, `k0=60`) — robust, no score
   calibration needed.
4. Return top-`k` globally, each hit: `{repo, kind, name, qualified_name, file, snippet,
   score, matched_via, freshness, drill_down:{repo, qualified_name}}`.

Default `repos=None` searches **all** registered repos (cross-repo discovery is the point);
pass `repos=[...]` to narrow. `kinds` filters doc/symbol.

## 8. Embeddings

`Embedder` calls the **gateway's OpenAI-compatible `/v1/embeddings`** (the same gateway
`codewiki` uses), GPU-served, with a configurable `embed_model`. Requests are **batched** at
index time. The query path embeds a single string.

- **Config (`repo_atlas` owns it):** `base_url`, `api_key`, `embed_model` (+ optional default
  read from `codewiki`'s stored creds). Kept separate from `codewiki`'s CLI config to keep
  boundaries clean.
- **Phase-1 prerequisite (Task 0):** verify the gateway exposes an embeddings model — record
  its **name + vector dimension** (`GET {base_url}/models`); the `vectors.dim` and brute-force
  cosine assume a fixed dimension.
- **GPU** is a gateway-side serving concern; `repo_atlas` only calls the endpoint. Confirm the
  embeddings model is GPU-served as part of Task 0.

## 9. MCP surface (`repo_atlas` server — separate from `repo_memory`)

All tools return the `repo_memory.contract.envelope` shape (`result`, `freshness`,
`provenance`, `warnings`, …), extended with per-hit provenance.

| Tool | Params | Returns |
|---|---|---|
| `find_related` | `query, repos=None, kinds=None, k=20` | ranked cross-repo hits (§7) |
| `prepare_change` | `target, repo` | context pack: module doc + target symbol + callers/callees + `assess_impact` blast radius + scoped conventions (`find_related` limited to `repo`) |
| `verify_grounding` | `symbols, repo` | per referenced symbol: exists? + nearest real matches (anti-hallucination) |
| `list_repos` | — | registry + freshness (indexed `repo_head` vs current git HEAD) |

Param specifics (Phase 1, to remove ambiguity):
- `prepare_change.target` is a **symbol `qualified_name` or a repo-relative file path** — the
  thing about to change.
- `verify_grounding.symbols` is a **list of symbol names / qualified_names** the caller (the
  agent) references; extracting identifiers from a raw code blob automatically is a Phase-2
  stretch goal, not Phase 1.

`prepare_change` / `verify_grounding` are **single-repo** (the repo being edited); `find_related`
is **all-repo by default**. Live graph drill-down beyond Phase 1 reuses `repo_memory`'s graph
tools.

Launch: `python -m repo_atlas` / a `repo-atlas` console script. Registered in Claude Code the
same way as `repo_memory` (`claude mcp add`).

## 10. Foundation touches (small, additive — inside Phase 1)

1. **`enumerate_all_nodes(client, *, project, page_size=200)`** in `repo_memory.graph.nodes` —
   paginate `forward.search_graph` with no filter to dump every symbol of a project. ~10 lines,
   reused by the indexer.
2. **`repo_atlas` endpoint config** (§8) — minimal, self-owned.
3. **Reuse `repo_memory.contract` + `grounding`** for envelope/freshness rather than reinventing.

Explicitly **not** doing: extracting a shared "common" package (`repo_atlas → repo_memory` is
fine layering; extraction is YAGNI until something forces it).

## 11. Scope & phases

- **Phase 1 (this spec):** registry + indexer + SQLite store + hybrid retrieval (**semantic
  included**) + the 4 tools, over the 3 `corpora` repos; the eval harness (§13).
  Implementation naturally splits into two plans, sequenced: **(1a) the `repo_atlas` system**
  (registry → indexer → store → retrieval → MCP tools) and **(1b) the validation harness**
  (task set + with/without runner + metrics), since 1b consumes 1a.
- **Phase 2:** richer live graph drill-down from a hit; freshness automation (auto-reindex on
  HEAD change); usage-example surfacing from call sites.
- **Later:** the feedback loop (gaining new knowledge).

## 12. Testing (correctness — "is it built right?")

Mirrors `repo_memory`'s conventions (offline by default; integration gated).

- **Offline unit tests** with a **stub embedder** (deterministic vectors), no gateway/CBM:
  heading chunker, RRF fusion, store upsert/query (FTS + cosine), registry/freshness logic,
  `verify_grounding` matching, envelope shape.
- **Gated integration test** (`@pytest.mark.integration`): index the 3 corpora (real CBM + real
  gateway embeddings) and run a real `find_related` + `prepare_change`, asserting grounded,
  fresh, non-empty results.

## 13. Validation / Eval (usefulness — "is it worth building?")

The core question: **does giving Claude Code these tools make it code/fix-bugs better?** This
is an evaluation, separate from correctness tests.

**Method — A/B "with vs without `repo_atlas`".** Each task is run twice by Claude Code under
identical conditions (same model, prompt, repo state): **baseline** (normal tools only) vs
**treatment** (`repo_atlas` MCP tools available). We reuse the existing
`engram/eval/runs/.../{with_,without_}` harness pattern. Condition order randomized; judge
blinded to condition.

**Task set** — ~15–30 curated tasks over the 3 corpora, each with a **ground-truth key**
(existing symbols/files a good solution should reference/reuse + a correctness rubric):

- *Development* tasks (a relevant building block exists) — e.g. "add a sepia filter to
  gpuimage" (key: `cgeImageFilter` base + sibling filters).
- *Bug-fixing* tasks (known defect + known fix) — e.g. "fix the JNI registration crash in
  ndk-samples".

**Metrics** — primary + diagnostics; the validation is the **with-vs-without delta**, reported
**per-task** (not just averaged, so a win can't hide a regression):

| Metric | Primary? | How measured |
|---|---|---|
| **Task success** | **Primary** | LLM judge w/ rubric vs ground-truth + spot human review |
| Hallucination rate | diagnostic | **objective** — % referenced symbols absent from the CBM graph |
| Prior-art reuse | diagnostic | **objective** — overlap of solution with the ground-truth key |
| Exploration cost | diagnostic | **objective** — tool calls / tokens to solution |

**Verdict:** `repo_atlas` is useful if **task success ↑** (primary), ideally corroborated by
hallucination ↓ / reuse ↑ / exploration ↓.

**Honesty guards:**

- Explicitly track the **context-pollution failure mode** — a "regressed" count surfaces any
  task where treatment did *worse*.
- Objective diagnostics (②③④) need no human judge and are hard to game; the judged primary
  (①) uses a rubric + blinding + multiple judge runs to cut noise.
- **Environment limitation:** the corpora don't build here (Android SDK, etc.), so task success
  is scored against the **ground-truth key + rubric**, not compile/test-pass.

The eval is a **repeatable harness**, so it doubles as a regression guard for future changes.

## 14. Risks & open questions

- **Gateway embeddings model** must exist + be GPU-served (Task 0 verifies; blocks semantic).
- **Retrieval precision** across heterogeneous repos — RRF is a reasonable default; the eval's
  reuse/exploration metrics will tell us if ranking needs tuning.
- **Judge reliability** for task success — mitigated by rubric + blinding + objective
  corroborators; some residual subjectivity remains.
- **Task-set construction cost** — curating ~15–30 tasks with ground-truth keys is the bulk of
  the eval effort; start with ~6–8 to prove the harness, then expand.
- **Naming** — `repo_atlas` is provisional.

## 15. Pointers

- [`docs/MVP.md`](../../MVP.md) — the single-repo `repo_memory` facade this builds on.
- [`docs/INTRODUCTION.md`](../../INTRODUCTION.md) — the close-the-loop vision (feed-back = the
  deferred next phase after this).
- [`docs/repo_memory-deploy.md`](../../repo_memory-deploy.md) — CBM launch (reused by the indexer).
- `engram/eval/runs/` — the with/without eval harness pattern reused in §13.
