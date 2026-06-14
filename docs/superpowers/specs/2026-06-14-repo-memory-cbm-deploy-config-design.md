# Design Spec: repo_memory — CBM Deployment & Configuration Layer (no fork)

- **Date:** 2026-06-14
- **Parent spec:** `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md` (M0–M5)
- **Builds on:** `docs/superpowers/specs/2026-06-14-repo-memory-m2-facade-design.md` (facade +
  `CBMClient`) and `2026-06-14-repo-memory-m3-hybrid-design.md`.
- **Status:** Draft for user review (approach + placement approved in brainstorming).

---

## 1. Context & Scope

`repo_memory` spawns CBM (`codebase-memory-mcp`) as a stdio subprocess: `build_app(cbm_command=…)`
constructs a `CBMClient`, and the server lifespan starts/stops it. To run that backend across
**ephemeral per-task sandboxes, a long-lived shared service, CI pipelines, and developer machines**,
each deployment needs different CBM settings (index location, worker count, log level, version pin).

CBM is explicitly built for configurable deployment **without source changes**: a single static
binary with zero runtime deps, runtime env vars (`CBM_CACHE_DIR`, `CBM_WORKERS`, `CBM_LOG_LEVEL`, …),
a `config` CLI, and per-project/global config files. The right answer is therefore a thin
**configuration/deployment layer inside `repo_memory`** that resolves per-environment settings and
injects them when it spawns CBM. **No fork of CBM.**

**In scope:** (1) `CBMClient` env/cwd passthrough; (2) a pure resolver + four built-in profiles;
(3) `server.main()` wiring; (4) unit + one gated integration test; (5) a deploy-recipes doc.

**Out of scope (deferred):** forking CBM or changing its features; graph write-back; managing CBM's
*own* config files (`.codebase-memory.json`, `config set`, including `auto_index`); committing
runnable infra (a `deploy/` dir); orchestrating CBM *installation* (we assume it is installable via
`uvx`/binary); any settings UI or server-side profile classifier.

## 2. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **No fork** — a config/deploy layer, not a customized CBM | CBM is config-driven; forking C/C++ adds maintenance + upstream divergence with **no** capability gain for a deployment need |
| D2 | The layer lives **entirely in `repo_memory/`** (knowledgeLoop); nothing in the CBM repo | `repo_memory` owns the CBM subprocess; keeps CBM as a pinned upstream dependency; travels cleanly into the planned repo merge |
| D3 | Settings are injected **at spawn** via `StdioServerParameters` `env`/`cwd` | The only path for `CBM_*` to reach the subprocess; `CBMClient` does not set these today |
| D4 | Explicitly **preserve** `HOME`/`XDG_CONFIG_HOME`/`APPDATA`/`LOCALAPPDATA`/`PATH`/`TMP`/`TEMP`/`USERPROFILE` | The MCP SDK merges our `env` over a *clean* `get_default_environment()`, not the parent env; CBM reads these |
| D5 | Profiles are **Python dicts in `deploy.py`** (`ephemeral`/`shared`/`ci`/`dev`) | Consistent with `model_profiles.py`; typed; no parsing/IO |
| D6 | Precedence **explicit env > profile > default** | 12-factor; mirrors the engine's "explicit-CLI-values-win" `Config` precedence |
| D7 | **v1 = env vars only**; CBM config-file management deferred | YAGNI; env covers the deployment knobs we need now |
| D8 | **Pin** the CBM version via a default constant, overridable per profile/env | Reproducible deploys; default `0.8.0` (latest tag) — executor confirms what the index resolves |
| D9 | Deploy artifacts as **doc snippets**, not a `deploy/` dir | YAGNI; recipes, not committed infra |
| D10 | Preserve graceful degrade; **add** fail-fast on an unwritable cache dir + worker-range check | A misconfigured deploy should fail loudly, not silently mis-locate the index |

## 3. Components (extend the M2 facade)

```
repo_memory/
├── deploy.py          # NEW: LaunchSpec + PROFILES + resolve_launch_spec() (pure)
├── graph/client.py    # EDIT: CBMClient.__init__ gains env=/cwd=, set on StdioServerParameters
└── server.py          # EDIT: build_app accepts cbm_env/cbm_cwd; main() resolves a profile and wires it
tests/
└── test_rm_deploy.py  # NEW: resolver precedence + per-profile expansion + client passthrough (offline)
                       #      + one gated integration test (cache-dir isolation)
docs/
└── repo_memory-deploy.md  # NEW: per-target recipes + the clean-env gotcha
```

Each unit has one purpose: **`deploy.py`** = config resolution (pure, testable offline);
**`client.py`** = spawn mechanics; **`server.py`** = wiring.

## 4. `deploy.py` — resolver + profiles

```python
@dataclass(frozen=True)
class LaunchSpec:
    command: list[str]        # e.g. ["uvx", "codebase-memory-mcp@0.8.0"]
    env: dict                 # CBM_* knobs + preserved passthrough vars
    cwd: Optional[str]        # usually None

DEFAULT_CBM_VERSION = "0.8.0"
PRESERVE_ENV = ("HOME","XDG_CONFIG_HOME","APPDATA","LOCALAPPDATA","PATH","TMP","TEMP","USERPROFILE")
KNOBS = ("CBM_CACHE_DIR","CBM_WORKERS","CBM_LOG_LEVEL","CBM_DIAGNOSTICS",
         "CBM_SEMANTIC_ENABLED","CBM_SEMANTIC_THRESHOLD","CBM_LSP_DISABLED","CBM_SQLITE_MMAP_SIZE")

PROFILES: dict[str, dict]   # name -> {"command_version": str|None, "env": {KNOB: value}}

def resolve_launch_spec(profile: str|None = None, environ: dict = os.environ,
                        *, cache_dir: str|None = None) -> LaunchSpec: ...
```

**Resolution (D6 precedence):** start from the named profile's `env` (or `dev` default) → overlay any
`CBM_*` / `REPO_MEMORY_CBM_*` values present in `environ` → overlay an explicit `cache_dir` arg.
Build `command` from `REPO_MEMORY_CBM_COMMAND` (full override) else `uvx codebase-memory-mcp@<version>`
(version from profile/env else `DEFAULT_CBM_VERSION`). Always merge `PRESERVE_ENV` (those present in
`environ`) into `env`.

**Controlling env vars:** `REPO_MEMORY_CBM_PROFILE` (select profile), `REPO_MEMORY_CBM_COMMAND`
(override the whole command, e.g. an absolute vendored-binary path), `REPO_MEMORY_CBM_VERSION`
(override the pin), plus any raw `CBM_*` knob passed straight through.

**Profiles (env only; values illustrative — finalize in the plan):**

| Profile | Intent | Key knobs |
|---|---|---|
| `dev` | local default = today's behavior | none (CBM defaults: cache `~/.cache/codebase-memory-mcp`) |
| `ephemeral` | per-task sandbox, fast, isolated | `CBM_CACHE_DIR=<per-task>` (required), `CBM_WORKERS` cgroup-aware, `CBM_LOG_LEVEL=warn` |
| `shared` | warm long-lived index on a volume | `CBM_CACHE_DIR=<persistent>` (required), larger `CBM_SQLITE_MMAP_SIZE`, `CBM_SEMANTIC_ENABLED=1` |
| `ci` | reproducible, restorable cache | pinned version (always), `CBM_CACHE_DIR=<restorable>`, `CBM_LOG_LEVEL=warn`, deterministic `CBM_WORKERS` |

`ephemeral`/`shared`/`ci` **require** a cache dir; if neither the profile, env, nor `cache_dir` arg
supplies a writable one, `resolve_launch_spec` raises a clear error (D10).

## 5. `graph/client.py` — env/cwd passthrough (keystone)

`CBMClient.__init__(self, command=None, *, call_timeout=30.0, env=None, cwd=None)` →
`StdioServerParameters(command=cmd[0], args=cmd[1:], env=env, cwd=cwd)`. Behavior is unchanged when
`env`/`cwd` are `None`. Add a docstring note: the SDK merges `env` over `get_default_environment()`,
so callers must include any non-`CBM_*` vars CBM needs (handled by `deploy.PRESERVE_ENV`).

## 6. `server.py` — wiring

- `build_app(..., cbm_command=None, cbm_env=None, cbm_cwd=None)` → `CBMClient(cbm_command, env=cbm_env, cwd=cbm_cwd)`.
- `main()`: `spec = resolve_launch_spec(os.environ.get("REPO_MEMORY_CBM_PROFILE"), os.environ)`;
  pass `spec.command/env/cwd` into `build_app`. Existing `REPO_MEMORY_WIKI_DIR` / `REPO_MEMORY_ENTITY_MAP`
  handling is unchanged. Graceful degrade (CBM down → wiki tools only) is unchanged.

## 7. Error handling / degradation

- **Unwritable / missing required cache dir** → fail fast with an actionable message (D10).
- **Invalid `CBM_WORKERS`** (non-int / out of 1–256) → drop it with a warning (CBM also range-checks).
- **CBM unavailable at runtime** → unchanged: `state.cbm = None`, wiki tools still work, warning surfaced.

## 8. Testing (1:1 with existing `test_rm_*` discipline, offline by default)

- `resolve_launch_spec`: env > profile > default precedence; each profile expands to the expected
  `command` + `env`; `PRESERVE_ENV` carries through; `REPO_MEMORY_CBM_COMMAND`/`_VERSION` overrides;
  a profile that requires a cache dir raises when none is supplied.
- `CBMClient`: `env`/`cwd` land on `StdioServerParameters` (assert on `_params`; no real subprocess);
  `env=None` reproduces today's params.
- **Gated** (`@pytest.mark.integration`): spawn CBM with a temp `CBM_CACHE_DIR`, index a tiny repo,
  assert the DB is created under that dir (isolation), and a second cache dir does not see it.

## 9. Internal phases (for the implementation plan)

- **(a)** `CBMClient` env/cwd passthrough + unit test.
- **(b)** `deploy.py` `LaunchSpec` + `PROFILES` + `resolve_launch_spec` + unit tests.
- **(c)** `server.py` `build_app`/`main()` wiring.
- **(d)** `docs/repo_memory-deploy.md` recipes (Docker shared service, CI cache-restore, dev `.mcp.json`,
  ephemeral per-task env) + the clean-env gotcha.
- **(e)** gated integration test + full offline suite (regression).

## 10. Non-Goals (deferred)

Fork / CBM feature changes; graph write-back; CBM config-file management (`.codebase-memory.json`,
`config set`, `auto_index`/`auto_index_limit`); a committed `deploy/` dir; CBM install orchestration;
profile selection by a classifier.

## 11. Open Questions / Risks

- **Published version vs tag:** `server.json` shows `0.7.0` but the latest tag/checkout is `v0.8.0`.
  The executor must confirm `uvx codebase-memory-mcp@<ver>` resolves on the target index before
  committing the `DEFAULT_CBM_VERSION` pin.
- **SDK clean-env contents** differ by platform; `PRESERVE_ENV` mitigates but the integration test
  must confirm CBM starts under the merged env on the target OS.
- **`auto_index` is a `config set` value persisted per cache dir, not an env var.** With v1 env-only,
  "fresh index per task" is achieved by an explicit `index_repository` call (CBM auto-syncs after the
  first index), not by a profile knob. Controlling `auto_index` declaratively is a config-file follow-up.
- **`cwd` semantics:** `repo_memory` passes repo paths to CBM tools explicitly (`index_repository
  repo_path=…`), so `cwd` mainly affects relative config discovery — keep it optional.

## 12. Coordination / Execution note

A separate session is **actively committing in `repo_memory/`**. The implementation plan must list
"coordinate with / sequence after the concurrent `repo_memory` work (rebase onto its latest HEAD;
re-confirm `CBMClient`/`build_app`/`server.main` signatures before editing)" as an explicit
**precondition**, since this plan edits `graph/client.py` and `server.py`.

### Related
- Parent: `docs/superpowers/specs/2026-06-14-codewiki-cbm-integration-design.md`
- Builds on: `docs/superpowers/specs/2026-06-14-repo-memory-m2-facade-design.md`,
  `docs/superpowers/specs/2026-06-14-repo-memory-m3-hybrid-design.md`
