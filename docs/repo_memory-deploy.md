# Deploying the CBM backend for repo_memory

`repo_memory` spawns `codebase-memory-mcp` (CBM) as a stdio subprocess. You pick a **profile** and
supply settings via environment variables; `repo_memory.deploy.resolve_launch_spec` turns those into
the CBM launch command + env. **CBM itself is unmodified** — a pinned upstream dependency.

## Profiles

| Profile | Use | Requires `CBM_CACHE_DIR` | Sets |
|---|---|---|---|
| `dev` | local default | no (CBM default `~/.cache/codebase-memory-mcp`) | — |
| `ephemeral` | per-task sandbox | yes | `CBM_LOG_LEVEL=warn` |
| `shared` | long-lived warm index | yes | `CBM_SEMANTIC_ENABLED=1`, `CBM_SQLITE_MMAP_SIZE=1073741824` |
| `ci` | reproducible, restorable cache | yes | `CBM_LOG_LEVEL=warn` |

Select with `REPO_MEMORY_CBM_PROFILE`. Any raw `CBM_*` var in the environment overrides the profile
(precedence: **explicit env > profile > default**).

## Controls

| Var | Effect |
|---|---|
| `REPO_MEMORY_CBM_PROFILE` | pick a profile (default `dev`) |
| `REPO_MEMORY_CBM_VERSION` | override the pinned CBM version |
| `REPO_MEMORY_CBM_COMMAND` | replace the whole launch command (e.g. an absolute vendored binary path) |
| `REPO_MEMORY_CBM_CWD` | working dir for the CBM subprocess (rarely needed) |
| `CBM_CACHE_DIR` | where CBM stores its index DB + config (per-task isolation) |
| `CBM_WORKERS` | parallel-index workers (1–256; set per cgroup quota in containers) |

## The clean-env gotcha

The MCP stdio client merges the env you pass over a **clean** `get_default_environment()`, **not** the
full parent environment. `repo_memory.deploy.PRESERVE_ENV` re-adds the vars CBM needs that are present
in your environment (`HOME`, `XDG_CONFIG_HOME`, `APPDATA`, `LOCALAPPDATA`, `PATH`, `TMP`, `TEMP`,
`USERPROFILE`). If you bypass `resolve_launch_spec` and build env yourself, include these or CBM may
fail to find its cache/config.

## Version pin

`DEFAULT_CBM_VERSION` (in `repo_memory/deploy.py`) pins the CBM version `uvx` fetches. **Confirm what
your package index actually serves before changing it:** as of this writing the CBM repo's
`server.json` says `0.7.0` and the latest git tag is `v0.8.0`, but the package index publishes
**`0.8.1`** (`0.7.0`/`0.8.0` do **not** resolve via `uvx`). Override per deployment with
`REPO_MEMORY_CBM_VERSION`, or replace the command entirely with `REPO_MEMORY_CBM_COMMAND`.

## Recipes

### Developer machine
```bash
# defaults are fine; just have CBM installable via uvx
export REPO_MEMORY_CBM_PROFILE=dev
```

### Ephemeral per-task sandbox
```bash
export REPO_MEMORY_CBM_PROFILE=ephemeral
export CBM_CACHE_DIR="$RUNNER_TEMP/cbm-$TASK_ID"   # unique per task; discarded with the sandbox
export CBM_WORKERS=4                                # match the sandbox's cgroup quota
# repo_memory triggers indexing explicitly via the CBM index_repository tool; CBM auto-syncs after.
```

### Long-lived shared service (Docker)
```dockerfile
FROM python:3.12-slim
RUN pip install uv
ENV REPO_MEMORY_CBM_PROFILE=shared
ENV CBM_CACHE_DIR=/data/cbm           # mount a persistent volume here
VOLUME /data/cbm
# ... install repo_memory + its wiki/entity_map artifacts, then run the server ...
```

### CI pipeline (cache restore)
```yaml
# pseudo-CI: pin the version, cache the index dir between runs
env:
  REPO_MEMORY_CBM_PROFILE: ci
  REPO_MEMORY_CBM_VERSION: "0.8.1"
  CBM_CACHE_DIR: ".cbm-cache"
steps:
  - uses: actions/cache@v4
    with:
      path: .cbm-cache
      key: cbm-${{ hashFiles('**/*.py') }}
  - run: <run repo_memory tasks>
```

> Confirm `uvx codebase-memory-mcp@<version>` resolves on your package index before pinning.
