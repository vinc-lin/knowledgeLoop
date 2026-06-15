# knowledgeLoop MVP — Setup & Run

A from-zero guide to installing knowledgeLoop and standing up the `repo_memory`
grounded-MCP facade against a target repo. For **what it is / architecture /
capabilities** see [`docs/MVP.md`](MVP.md); for the full **deploy-profile
reference** see [`docs/repo_memory-deploy.md`](repo_memory-deploy.md). This doc is
the actionable install/run path.

## How CBM is consumed (read this first)

`repo_memory` does **not** bundle or vendor the Codebase-Memory-MCP (CBM) code
graph. It spawns CBM **on demand as a stdio subprocess** via `uvx`, pinned to a
published version (`uvx codebase-memory-mcp@0.8.1`). For the MVP this is a
**deliberate choice** — CBM stays an unmodified, pinned upstream dependency and is
not merged into this repo (see [`docs/MVP.md`](MVP.md) §6). The practical
consequence: **standing this up needs `uv` on the host and network access to the
package index on first run** (the fetch is cached afterward).

If CBM can't be fetched/spawned, the server still starts and **wiki-only tools
keep working** — graph/hybrid tools degrade gracefully rather than crash.

## 1. Prerequisites

| Need | Why |
|---|---|
| **Python 3.12+** | `requires-python = ">=3.12"` |
| **Node.js ≥14** | Mermaid diagram validation during `codewiki generate` |
| **`uv`** (provides `uvx`) | spawns CBM; also used to create the venv |
| **Network access to the package index** | `uvx` fetches `codebase-memory-mcp@0.8.1` on first run (cached after) |

Install `uv` (provides `uvx`):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Install knowledgeLoop

From the repository root (this installs **both** the `codewiki` CLI and the
`repo_memory` package):

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"   # drop [dev] for runtime-only
```

## 3. Verify CBM is reachable

Pre-warm / confirm the pinned CBM resolves via `uvx` before first use:

```bash
uvx codebase-memory-mcp@0.8.1 --help
```

**Version pin gotcha:** it must be `0.8.1`. The CBM repo's `server.json` says
`0.7.0` and the latest git tag is `v0.8.0`, but **only `0.8.1` is published** to the
index (`0.7.0`/`0.8.0` do **not** resolve via `uvx`). Override per deployment with
`REPO_MEMORY_CBM_VERSION`, or replace the whole spawn command with
`REPO_MEMORY_CBM_COMMAND` (e.g. an absolute path to a locally built binary).

> **Air-gapped / no network?** `uvx` can't fetch CBM, so you'll run wiki-only.
> Bundling CBM into this repo (the "repo merge") is **deliberately deferred** for
> the MVP — see [`docs/MVP.md`](MVP.md) §6. Lightweight workaround: pre-cache the
> `0.8.1` wheel, or point `REPO_MEMORY_CBM_COMMAND` at a pre-installed binary.

## 4. Generate the wiki (produce)

Run from the **target repo's** directory. A provider/model must be configured first
(`codewiki config set …`; see [`CLAUDE.md`](../CLAUDE.md) "Common commands").

```bash
codewiki generate --output ./wiki-docs --github-pages --verbose
```

Produces `./wiki-docs/*.md`, `module_tree.json`, `first_module_tree.json`,
`metadata.json` (+ `index.html`). `metadata.generation_info.commit_id` is the
freshness anchor used later.

## 5. Launch the `repo_memory` MCP server (consume)

Installing the package registers a **`repo-memory`** console script
(`repo_memory.server:main`); you can equivalently run **`python -m repo_memory`**.
Either runs the facade over **stdio**:

```bash
# run from the target repo (REPO_MEMORY_REPO_PATH defaults to the cwd)
.venv/bin/repo-memory
# equivalent:
.venv/bin/python -m repo_memory
```

Key environment variables (full list + CBM knobs in
[`docs/MVP.md`](MVP.md) §3 and [`docs/repo_memory-deploy.md`](repo_memory-deploy.md)):

| Env var | Default | Purpose |
|---|---|---|
| `REPO_MEMORY_WIKI_DIR` | `wiki-docs` | where the generated wiki bundle lives |
| `REPO_MEMORY_ENTITY_MAP` | `entity_map.json` | Wiki↔Graph bridge artifact path |
| `REPO_MEMORY_REPO_PATH` | cwd | repo root (used by `refresh_index`) |
| `REPO_MEMORY_CBM_PROFILE` | `dev` | deploy profile (`dev`/`ephemeral`/`shared`/`ci`) |

Register it in an MCP client (use **absolute** paths):

```json
{
  "mcpServers": {
    "repo_memory": {
      "command": "/abs/path/to/.venv/bin/repo-memory",
      "args": [],
      "env": {
        "REPO_MEMORY_REPO_PATH": "/abs/path/to/target/repo",
        "REPO_MEMORY_WIKI_DIR": "/abs/path/to/target/repo/wiki-docs"
      }
    }
  }
}
```

> The **doc-generation** side is a separate MCP server with its own runner —
> `python -m codewiki.mcp.server` (tools: `generate_docs`, `analyze_repo`,
> `get_module_tree`). `repo_memory` is the consume side.

> For the **Claude Code**-specific registration (`claude mcp add`), permission
> allow-listing, and natural-language usage, see **§7 (Use it in Claude Code)**.

## 6. Bootstrap the graph + bridge (first run)

On a fresh setup `entity_map.json` doesn't exist yet and the repo isn't indexed in
CBM, so graph/hybrid tools degrade with `repo not indexed in CBM (run
refresh_index)`. **Call the `refresh_index` tool once**: it indexes the repo in CBM
and writes `entity_map.json` with `graph_commit = HEAD`. After that the
graph/hybrid tools and freshness gates work.

> Manual/offline alternative: the offline join `build_and_save` in
> `repo_memory/entity_map_build.py` (see [`docs/MVP.md`](MVP.md) §3(b)).

## 7. Use it in Claude Code

Register the server once, then query the repo in natural language. Use **absolute
paths** (env values resolve from the server's own CWD, not from the target repo).

```bash
claude mcp add repo-memory --scope user \
  -e REPO_MEMORY_REPO_PATH=/abs/target/repo \
  -e REPO_MEMORY_WIKI_DIR=/abs/target/repo/wiki-docs \
  -e REPO_MEMORY_ENTITY_MAP=/abs/target/repo/entity_map.json \
  -e CBM_CACHE_DIR=$HOME/cbm-cache \
  -- /abs/.venv/bin/python -m repo_memory
```

- `--scope user` makes it available in every project; use `--scope local`/`project`
  to limit it. The server name (`repo-memory`) is your choice. The generic
  `mcpServers` JSON in §5 is the equivalent for any MCP client (Claude Desktop, IDEs).
- **Restart the Claude Code session** — a running session does *not* pick up a
  newly added server. Then run **`/mcp`** to confirm `repo-memory` is *connected*
  (the panel shows status + a tool count, not a clickable tool list).

**Query it** by asking in natural language — tools are auto-routed (you can't
slash- or @-invoke them). Name the server to nudge routing:

| Ask | Routes to |
|---|---|
| "Use repo-memory for an architecture overview" | `get_repo_overview` / `get_architecture` |
| "Which real files implement the `<X>` module?" | `get_related_files` (wiki→code bridge) |
| "Trace the callers of `<fn>` and show its source" | `trace_symbol` → `get_code_snippet` |
| "What's the blast radius of my current changes?" | `assess_impact` (fail-closed) |
| "A tool said stale-graph — re-index it" | `refresh_index` |

**Skip the per-call approval prompt** — these are read-only query tools, so
allow-list the whole server in `~/.claude/settings.json` (or project
`.claude/settings.json`):

```json
{ "permissions": { "allow": ["mcp__repo-memory__*"] } }
```

(Single tool: `mcp__repo-memory__get_repo_overview`; globs work *after* the literal
`mcp__repo-memory__` prefix. Stdio servers don't auto-reconnect — restart the
session if one dies, or after any config change.)

> One server = one target repo (bound by its env). Register a second server under a
> different name (e.g. `repo-memory-foo`) to query another repo.

## 8. Test it against a read-only corpus

To exercise the MVP on a shared / read-only repo (e.g. a pinned `~/code/corpora`
tree) without polluting it:

- **Keep the corpus read-only.** Generate the wiki bundle and `entity_map.json` into
  an **external** scratch dir — `codewiki generate --output /abs/scratch/<repo>`
  with an **absolute** path (a relative `--output` lands inside the read-only tree).
  CBM only *reads* `REPO_MEMORY_REPO_PATH`; all writes go to the scratch paths.
- **Put `CBM_CACHE_DIR` on a local filesystem.** CBM writes a SQLite/WAL DB — keep it
  off network/9p (v9fs) mounts (e.g. under `$HOME`), or indexing can fail.
- **Freshness reaches `fresh`** when the corpus is a real git repo: the server
  derives `repo_head` via `git rev-parse HEAD` of `REPO_MEMORY_REPO_PATH` (override
  with `REPO_MEMORY_REPO_HEAD`), and `refresh_index` writes `graph_commit = HEAD`.
- **Confirm the corpus stayed clean:** on a 9p/v9fs mount `git status` reports every
  file as modified (filemode bits only) — use `git -c core.fileMode=false status` to
  see real content changes.

A repeatable produce→bridge→consume smoke harness lives at
[`scripts/ndk_mvp_smoke.py`](../scripts/ndk_mvp_smoke.py): point it at any repo via
the same env vars and it loads the wiki, starts CBM, runs `refresh_index`, then
drives the wiki/graph/hybrid tools, printing each envelope's freshness + provenance.

## 9. Verify

- Wiki tools (no CBM needed): `get_repo_overview`, `list_modules`.
- Graph tools (after `refresh_index`): `get_architecture`, `search_code_graph`.
- Run the offline test suite (command + notes in [`docs/MVP.md`](MVP.md) §5):
  ```bash
  .venv/bin/python -m pytest tests/ -p no:cacheprovider -m "not integration" --no-cov -s
  ```

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `repo-memory` not visible after `claude mcp add` | A running session doesn't load new servers — **restart the Claude Code session**, then `/mcp`. |
| Graph tools return `repo not indexed in CBM (run refresh_index)` | Expected on first run — call `refresh_index`. |
| Everything degrades to wiki-only | CBM didn't spawn. Check `uv`/`uvx` on `PATH`, network access, and that `0.8.1` resolves (`uvx codebase-memory-mcp@0.8.1 --help`). |
| CBM spawns but can't find its cache/config | The MCP SDK merges child env over a **clean** environment; `deploy.PRESERVE_ENV` re-injects `HOME/PATH/…`. If you build env yourself, include them — see [`docs/repo_memory-deploy.md`](repo_memory-deploy.md). |
| Need a different CBM build | Set `REPO_MEMORY_CBM_VERSION`, or override the whole command with `REPO_MEMORY_CBM_COMMAND`. |
| Freshness stuck at `unverified` | No `repo_head`: `REPO_MEMORY_REPO_PATH` isn't a git repo (set `REPO_MEMORY_REPO_HEAD`), CBM didn't spawn, or `entity_map.graph_commit` is null — run `refresh_index`. |

## Pointers

- [`docs/MVP.md`](MVP.md) — MVP spec: architecture, the 12 tools, guarantees, non-goals.
- [`docs/repo_memory-deploy.md`](repo_memory-deploy.md) — deploy-profile operator guide (profiles, knobs, recipes).
- [`docs/close-loop-workflow.md`](close-loop-workflow.md) — produce/bridge/consume/feed-back narrative.
- [`CLAUDE.md`](../CLAUDE.md) — high-signal repo essentials & common commands.
