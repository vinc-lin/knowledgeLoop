# Applying knowledgeLoop to a new repo

A task-oriented runbook for pointing this toolchain at **any** repository and ending up with
queryable, agent-consumable knowledge. For deep reference see `docs/SETUP.md` (install + deploy),
`docs/CODEWIKI.md` (generation), `docs/MVP.md` / `docs/close-loop-workflow.md` (the consume layer),
and `docs/repo_memory-deploy.md` (CBM deploy profiles). This guide ties them into one flow.

> The internal package and the three console scripts are named **`codewiki`**, **`repo-memory`**,
> **`repo-atlas`** — `codewiki` is intentional (this is CodeWiki copied verbatim); do not rename.

## The pipeline, and where you can stop

```
  ┌─────────────┐    ┌──────────────────┐    ┌────────────────────────┐
  │ Layer 1     │    │ Layer 2          │    │ Layer 3                │
  │ PRODUCE     │──► │ BRIDGE + SERVE   │──► │ CROSS-REPO ATLAS       │
  │ codewiki    │    │ repo-memory      │    │ repo-atlas             │
  │ → a wiki    │    │ → 1-repo MCP     │    │ → many-repo MCP        │
  └─────────────┘    └──────────────────┘    └────────────────────────┘
   browsable docs     grounded Q&A on         "find prior art across all
                      ONE repo, agent-ready    my repos" retrieval, agent-ready
```

It is **layered** — stop wherever your need ends:
- **Just want browsable architecture docs?** Do Layer 1 only.
- **Want an agent to answer grounded questions about one repo?** Layers 1–2.
- **Want cross-repo "find the existing helper" retrieval?** All three.

---

## Layer 0 — One-time setup (once per machine)

**Prerequisites:** Python **3.12+**, **Node.js ≥14** (Mermaid diagram validation during generation),
and **`uv`** (creates the venv and, later, spawns the CBM graph backend via `uvx`).

```bash
# from the knowledgeLoop repo root — no .venv is committed, so you must create one
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"   # drop [dev] for runtime-only
```

This registers all three console scripts: `codewiki`, `repo-memory`, `repo-atlas`
(`pyproject.toml` `[project.scripts]`).

**Directory convention (important):** keep produced artifacts **outside** the target repo, especially
if the repo is a read-only corpus checkout. The real e2e run used:

| What | Where |
|---|---|
| target repos (read-only) | `/mnt/x/code/corpora/<repo>` |
| produced wikis + bridges  | `/home/vinc/e2e-knowledgeloop/<repo>/docs` + `.../entity_map.json` |
| cross-repo atlas DB + registry | `/home/vinc/repo-atlas-eval-full/atlas.db` + `atlas.toml` |

Substitute your own roots below; the commands use `$REPO`, `$WIKI`, `$VENV` placeholders.

```bash
REPO=/path/to/target-repo            # the repo you want to understand (a git checkout)
WIKI=/path/to/knowledge/<repo>/docs  # produced wiki bundle (OUTSIDE $REPO)
VENV=/abs/path/to/knowledgeLoop/.venv # absolute path to the venv from Layer 0
```

---

## Layer 1 — PRODUCE: generate a wiki for the repo

### 1a. Configure a provider/model (once; persisted to `~/.codewiki/config.json`)

```bash
# API mode (OpenAI-compatible gateway shown; also: anthropic | bedrock | azure-openai)
CODEWIKI_NO_KEYRING=1 $VENV/bin/codewiki config set \
  --provider openai-compatible --api-key KEY --base-url URL/v1 \
  --main-model deepseek-chat --cluster-model deepseek-chat

# OR subscription mode (no API key — routes through your local claude/codex CLI; run `claude login` first)
$VENV/bin/codewiki config set --provider claude-code --main-model claude-sonnet-4-5

CODEWIKI_NO_KEYRING=1 $VENV/bin/codewiki config show      # resolved profile (output cap, granularity)
CODEWIKI_NO_KEYRING=1 $VENV/bin/codewiki config validate  # tests gateway connectivity / CLI availability
```

- `CODEWIKI_NO_KEYRING=1` forces file-based creds (`~/.codewiki/credentials.json`) in headless
  environments without a system keychain.
- **Switching models is a one-liner** — `codewiki config set --main-model qwen3` — and the operational
  profile (clustering granularity, request budget, token-param style) is derived from the model's
  output cap automatically. No manual token math. If a gateway renames a model id so the built-in
  registry doesn't match it, teach it: `codewiki config set-model <id> --output-cap N --request-limit N`.

### 1b. Generate (run from the target repo's directory)

```bash
cd "$REPO"
$VENV/bin/codewiki generate --output "$WIKI" --github-pages --verbose
```

| flag | effect |
|---|---|
| `--output / -o` | output dir. **Use an absolute path** for a read-only repo — a relative path lands *inside* it. |
| `--github-pages` | also emit `index.html` (browsable wiki viewer) |
| `--verbose / -v` | per-stage progress (the only log-level lever — there is no env knob) |
| `--concurrency N` | document N top-level modules in parallel (default 1 = sequential) |
| `--update` | incremental: diff `HEAD` vs `metadata.json` commit_id, regenerate only affected modules |
| `--no-cache` | force full regeneration |
| `--include/-i, --exclude/-e, --focus/-f` | scope which files/modules are documented |

**You get** (in `$WIKI`): per-module `<Module>.md`, `overview.md`, `module_tree.json`,
`first_module_tree.json`, `metadata.json`, and `index.html` (with `--github-pages`).
`metadata.json` → `generation_info.commit_id` is the **freshness anchor** the later layers read.

> **Stop here** if you only wanted browsable, architecture-aware docs. Open `$WIKI/index.html`.

---

## Layer 2 — BRIDGE + SERVE: grounded MCP for ONE repo (`repo-memory`)

`repo-memory` is a stdio MCP server that fuses the Layer-1 wiki (the *what/why*) with the **CBM code
graph** (the *where* — real files + symbols, call paths) behind one freshness-aware endpoint. CBM is
spawned on demand as `uvx codebase-memory-mcp@0.8.1` (exact pin — `0.7.0`/`0.8.0` do **not** resolve).

### 2a. Launch it (fully env-var driven — no CLI flags)

```bash
REPO_MEMORY_REPO_PATH="$REPO" \
REPO_MEMORY_WIKI_DIR="$WIKI" \
REPO_MEMORY_ENTITY_MAP="$(dirname "$WIKI")/entity_map.json" \
CBM_CACHE_DIR="$HOME/cbm-cache" \
$VENV/bin/repo-memory          # equivalently: $VENV/bin/python -m repo_memory
```

### 2b. Bootstrap the graph + bridge — call `refresh_index` once

On first run the bridge artifact `entity_map.json` doesn't exist yet, so graph/hybrid tools degrade
with *"repo not indexed in CBM (run refresh_index)"*. Call the **`refresh_index`** MCP tool once: it
indexes the repo in CBM and writes `entity_map.json` with `graph_commit=HEAD`. (It does **not**
regenerate the wiki — re-run Layer 1 `--update` for that.)

### 2c. Register with your agent (Claude Code)

```bash
claude mcp add repo-memory --scope user \
  -e REPO_MEMORY_REPO_PATH="$REPO" \
  -e REPO_MEMORY_WIKI_DIR="$WIKI" \
  -e REPO_MEMORY_ENTITY_MAP="$(dirname "$WIKI")/entity_map.json" \
  -e CBM_CACHE_DIR="$HOME/cbm-cache" \
  -- $VENV/bin/python -m repo_memory
```

Restart the session; `/mcp` should show `repo-memory` connected. **Use absolute paths** — env values
resolve from the server's own CWD, not the target repo.

**The 12 tools** (every response carries a freshness + provenance envelope):
`get_repo_overview` (start here), `list_modules`, `search_wiki`, `get_module_doc` *(wiki)* ·
`get_related_files` *(wiki→source bridge)* · `search_code_graph`, `trace_symbol`, `get_code_snippet`,
`get_architecture` *(CBM graph)* · `explain_with_sources`, `assess_impact` *(hybrid)* ·
`refresh_index` *(recovery)*. Freshness is `fresh | stale-wiki | stale-graph | unverified`;
`assess_impact` is the only fail-closed (gating) tool. If CBM can't be fetched/spawned the server
still starts and wiki-only tools keep working.

> **Stop here** if you want grounded Q&A on a single repo.

---

## Layer 3 — CROSS-REPO ATLAS: retrieval across many repos (`repo-atlas`)

`repo-atlas` indexes wiki-doc + symbol "units" from **every registered repo** into one SQLite store
(FTS5 keyword + vector cosine), fuses them with RRF, and serves 4 MCP tools. CBM is touched only at
**index** time; queries hit only SQLite.

### 3a. Write the registry `atlas.toml`

```toml
[[repo]]
name = "android-gpuimage-plus"
repo_path = "/mnt/x/code/corpora/android-gpuimage-plus"
wiki_dir  = "/home/vinc/e2e-knowledgeloop/android-gpuimage-plus/docs"
entity_map = "/home/vinc/e2e-knowledgeloop/android-gpuimage-plus/entity_map.json"  # optional

[[repo]]
name = "libxcam"
repo_path = "/mnt/x/code/corpora/libxcam"
wiki_dir  = "/home/vinc/e2e-knowledgeloop/libxcam/docs"
```

`name`, `repo_path`, `wiki_dir` are required per `[[repo]]`; `entity_map` is optional (carried for
future use — the current index/retrieve path uses the wiki docs + a fresh CBM enumeration, not the
entity_map).

### 3b. Index (needs an embeddings gateway)

`repo-atlas` needs an **OpenAI-compatible `/v1/embeddings`** endpoint, and the **same embedding model
must be used at index time and query time** (a mismatch silently corrupts cosine ranking).

```bash
REPO_ATLAS_DB=/abs/atlas.db \
REPO_ATLAS_REGISTRY=/abs/atlas.toml \
REPO_ATLAS_BASE_URL=http://127.0.0.1:11500/v1 \
REPO_ATLAS_API_KEY=local \
REPO_ATLAS_EMBED_MODEL=bge-m3 \
$VENV/bin/python -m repo_atlas index --all     # or: index --repo <name>
```

Prints `indexed <name>: <n> units` per repo. Re-indexing is per-repo idempotent
(`index --repo NAME` refreshes just that repo). The DB is large (~0.8–1.4 GB for 3 mid-size repos)
and machine-specific — keep it out of git.

### 3c. Serve + register

```bash
$VENV/bin/python -m repo_atlas            # default subcommand = serve (stdio MCP); also: repo_atlas serve
```

`mcp.json` for an MCP client (same env as 3b):

```json
{ "mcpServers": { "repo-atlas": {
  "command": "/abs/knowledgeLoop/.venv/bin/python",
  "args": ["-m", "repo_atlas"],
  "env": { "REPO_ATLAS_DB": "/abs/atlas.db",
           "REPO_ATLAS_REGISTRY": "/abs/atlas.toml",
           "REPO_ATLAS_BASE_URL": "http://127.0.0.1:11500/v1",
           "REPO_ATLAS_API_KEY": "local",
           "REPO_ATLAS_EMBED_MODEL": "bge-m3" } } } }
```

**The 4 tools:** `find_related(query, repos?, kinds?, k?)` (hybrid retrieval; returns grouped
`{docs, symbols}` by default), `verify_grounding(symbols, repo)` (do these symbols exist? + nearest
matches), `prepare_change(target, repo)` (nearest symbol + conventions + related),
`list_repos()` (indexed units + freshness per repo). Tools that target one repo take a `repo` arg.

---

## Applying to MANY repos (the pattern)

1. For **each** repo, do Layer 1 (`codewiki generate`). Optionally Layer 2 (`refresh_index` to build
   its `entity_map.json` + CBM index) if you want per-repo grounded Q&A too.
2. List them all in **one** `atlas.toml`.
3. `repo_atlas index --all` once → a single cross-repo MCP an agent queries with `find_related`.

To refresh after a repo changes: re-run Layer 1 `--update` for that repo, then
`repo_atlas index --repo <name>`. `list_repos` shows `fresh`/`stale` (indexed head vs current HEAD).

---

## Worked example — `android-gpuimage-plus`, end to end

Real paths from the e2e run (`metadata.json`: 2786 components / 474 leaf modules / `deepseek-chat`;
atlas index: 33903 units):

```bash
VENV=/home/vinc/code/knowledgeLoop/.venv
REPO=/mnt/x/code/corpora/android-gpuimage-plus
WIKI=/home/vinc/e2e-knowledgeloop/android-gpuimage-plus/docs

# L1 produce
cd "$REPO"
$VENV/bin/codewiki generate --output "$WIKI" --github-pages --verbose

# L2 bridge + serve (then call refresh_index once from the agent)
REPO_MEMORY_REPO_PATH="$REPO" REPO_MEMORY_WIKI_DIR="$WIKI" \
REPO_MEMORY_ENTITY_MAP="$(dirname "$WIKI")/entity_map.json" CBM_CACHE_DIR="$HOME/cbm-cache" \
$VENV/bin/repo-memory

# L3 add to atlas.toml, then index across all repos
REPO_ATLAS_DB=/home/vinc/repo-atlas-eval-full/atlas.db \
REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-eval-full/atlas.toml \
REPO_ATLAS_BASE_URL=http://127.0.0.1:11500/v1 REPO_ATLAS_API_KEY=local REPO_ATLAS_EMBED_MODEL=bge-m3 \
$VENV/bin/python -m repo_atlas index --all
```

---

## Quick reference

| Layer | Command | Env it reads |
|---|---|---|
| 0 setup | `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"` | — |
| 1 configure | `codewiki config set --provider … --main-model …` | `CODEWIKI_NO_KEYRING` |
| 1 produce | `codewiki generate --output <abs> --github-pages` (from repo dir) | — |
| 2 serve | `repo-memory` / `python -m repo_memory` | `REPO_MEMORY_REPO_PATH`, `_WIKI_DIR`, `_ENTITY_MAP`, `CBM_CACHE_DIR` |
| 2 register | `claude mcp add repo-memory --scope user -e … -- <venv>/python -m repo_memory` | — |
| 3 index | `python -m repo_atlas index --all` | `REPO_ATLAS_DB`, `_REGISTRY`, `_BASE_URL`, `_API_KEY`, `_EMBED_MODEL` |
| 3 serve | `python -m repo_atlas` (default = serve) | same as index |

---

## Gotchas that actually bite

- **Run `codewiki generate` from the target repo's directory** — the repo is `cwd`, not a CLI arg.
- **Absolute `--output`** for a read-only corpus; a relative path writes inside the (possibly
  read-only) tree.
- **CBM is pinned to exactly `0.8.1`** — `0.7.0`/`0.8.0` don't resolve via `uvx`, even though git
  tags/`server.json` suggest otherwise. Pre-warm with `uvx codebase-memory-mcp@0.8.1 --help`.
- **First `repo-memory` run needs `refresh_index`** to build `entity_map.json` + the CBM index;
  before that, graph/hybrid tools degrade (they don't crash).
- **Embedding model must match** between `repo_atlas index` and query time. `REPO_ATLAS_REGISTRY`
  defaults to a *cwd-relative* `atlas.toml` — set it explicitly.
- **Keep `CBM_CACHE_DIR` (and the atlas DB) on a local FS**, not a 9p/v9fs mount — CBM writes SQLite/WAL.
  On v9fs, `git status` shows every file modified (filemode bits); use `git -c core.fileMode=false status`.
- **Small-output models** (e.g. DeepSeek 8K): the profile shrinks clustering granularity so modules
  split; request budgets are intentionally fail-fast (parent-recovery). Don't "fix" failures by
  raising the request limit.
- **Use absolute paths in every MCP registration** — env resolves from the server's CWD, not the repo.

## See also

- `docs/SETUP.md` — install, deploy profiles, read-only-corpus recipe (the reference for Layers 1–2).
- `docs/CODEWIKI.md` — full generation provider matrix + flags.
- `docs/MVP.md`, `docs/close-loop-workflow.md` — the consume layer's 12 tools, guarantees, freshness.
- `docs/repo_memory-deploy.md` — CBM deploy profiles (`dev`/`ephemeral`/`shared`/`ci`) + version pin.
- `docs/repo-atlas-evaluation.md` — how the cross-repo retrieval was evaluated.
- `scripts/run_eval_arms.sh` — a worked, preflighted multi-env runner (a good config example).
