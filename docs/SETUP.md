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

`repo_memory` has a `main()` but **no console-script / `python -m` runner yet**, so
launch it by invoking `main()` directly with the venv's Python. It serves over
**stdio**:

```bash
# run from the target repo (REPO_MEMORY_REPO_PATH defaults to the cwd)
.venv/bin/python -c "from repo_memory.server import main; main()"
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
      "command": "/abs/path/to/.venv/bin/python",
      "args": ["-c", "from repo_memory.server import main; main()"],
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

## 6. Bootstrap the graph + bridge (first run)

On a fresh setup `entity_map.json` doesn't exist yet and the repo isn't indexed in
CBM, so graph/hybrid tools degrade with `repo not indexed in CBM (run
refresh_index)`. **Call the `refresh_index` tool once**: it indexes the repo in CBM
and writes `entity_map.json` with `graph_commit = HEAD`. After that the
graph/hybrid tools and freshness gates work.

> Manual/offline alternative: the offline join `build_and_save` in
> `repo_memory/entity_map_build.py` (see [`docs/MVP.md`](MVP.md) §3(b)).

## 7. Verify

- Wiki tools (no CBM needed): `get_repo_overview`, `list_modules`.
- Graph tools (after `refresh_index`): `get_architecture`, `search_code_graph`.
- Run the offline test suite (command + notes in [`docs/MVP.md`](MVP.md) §5):
  ```bash
  .venv/bin/python -m pytest tests/ -p no:cacheprovider -m "not integration" --no-cov -s
  ```

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Graph tools return `repo not indexed in CBM (run refresh_index)` | Expected on first run — call `refresh_index`. |
| Everything degrades to wiki-only | CBM didn't spawn. Check `uv`/`uvx` on `PATH`, network access, and that `0.8.1` resolves (`uvx codebase-memory-mcp@0.8.1 --help`). |
| CBM spawns but can't find its cache/config | The MCP SDK merges child env over a **clean** environment; `deploy.PRESERVE_ENV` re-injects `HOME/PATH/…`. If you build env yourself, include them — see [`docs/repo_memory-deploy.md`](repo_memory-deploy.md). |
| Need a different CBM build | Set `REPO_MEMORY_CBM_VERSION`, or override the whole command with `REPO_MEMORY_CBM_COMMAND`. |
| Freshness stuck at `unverified` | No `repo_head` match — `metadata.generation_info.commit_id` is null (regenerate the wiki in a git repo so HEAD is captured). |

## Pointers

- [`docs/MVP.md`](MVP.md) — MVP spec: architecture, the 12 tools, guarantees, non-goals.
- [`docs/repo_memory-deploy.md`](repo_memory-deploy.md) — deploy-profile operator guide (profiles, knobs, recipes).
- [`docs/close-loop-workflow.md`](close-loop-workflow.md) — produce/bridge/consume/feed-back narrative.
- [`CLAUDE.md`](../CLAUDE.md) — high-signal repo essentials & common commands.
