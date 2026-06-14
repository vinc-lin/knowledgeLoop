# repo_memory CBM Deployment & Configuration Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `repo_memory` launch its CBM (`codebase-memory-mcp`) backend with per-deployment settings — across ephemeral per-task sandboxes, a shared long-lived service, CI, and dev machines — by injecting env/cwd at spawn time, with **no fork of CBM**.

**Architecture:** A pure resolver (`repo_memory/deploy.py`) turns a named profile + environment into a `LaunchSpec(command, env, cwd)`; `CBMClient` gains `env`/`cwd` passthrough onto `StdioServerParameters`; `server.main()` resolves a profile and wires the spec into `build_app`. CBM stays an unmodified, pinned upstream dependency.

**Tech Stack:** Python 3.12, `mcp` SDK (`StdioServerParameters`), pytest / pytest-asyncio. Design spec: `docs/superpowers/specs/2026-06-14-repo-memory-cbm-deploy-config-design.md`.

---

## File Structure

- `repo_memory/deploy.py` — **NEW**. `LaunchSpec`, `DeployConfigError`, `PROFILES`, `resolve_launch_spec()`. Pure; only reads the passed `environ`.
- `repo_memory/graph/client.py` — **MODIFY**. `CBMClient.__init__` gains `env=`/`cwd=`, set on `StdioServerParameters`.
- `repo_memory/server.py` — **MODIFY**. `build_app` gains `cbm_env`/`cbm_cwd`; `main()` resolves a profile and passes the spec.
- `tests/test_rm_deploy.py` — **NEW**. Offline unit tests for the resolver, the client passthrough, and the server wiring; one gated integration test.
- `docs/repo_memory-deploy.md` — **NEW**. Per-target deploy recipes + the clean-env gotcha.

**Conventions (match existing repo):** test files are gitignored — add new ones with `git add -f` (see `CLAUDE.md`). Run tests with `.venv/bin/python -m pytest <path> -p no:cacheprovider`. The repo's pyproject enables `--cov`; if `pytest-cov` is missing, append `--no-cov`. The `@pytest.mark.integration` marker is already used in `tests/test_rm_integration.py`.

---

## Task 0: Preconditions (no code — do this first)

The `feat/repo-memory-m0-m1` branch is being developed by another session concurrently. This plan edits `graph/client.py` and `server.py`, so confirm reality before editing.

- [ ] **Step 1: Sync and isolate**

```bash
cd knowledgeLoop
git fetch --all
git status                      # working tree should be clean except expected files
git log --oneline -5            # note current HEAD of feat/repo-memory-m0-m1
git switch -c feat/repo-memory-cbm-deploy   # isolate this work on its own branch
```

- [ ] **Step 2: Re-confirm the signatures this plan assumes still exist**

```bash
grep -n "def __init__" repo_memory/graph/client.py        # expect: CBMClient.__init__(self, command=None, *, call_timeout=30.0)
grep -n "def build_app" repo_memory/server.py             # expect: build_app(*, wiki_dir, entity_map_path, repo_head=None, cbm_command=None)
grep -n "def main" repo_memory/server.py                  # expect: main() reads REPO_MEMORY_WIKI_DIR / REPO_MEMORY_ENTITY_MAP, builds, .run(transport="stdio")
```

If any signature has drifted from the above, adapt the edits in Tasks 1 and 3 to the current code (same intent: add `env`/`cwd` passthrough and resolver wiring).

- [ ] **Step 3: Confirm the CBM version pin resolves**

```bash
uvx codebase-memory-mcp@0.8.0 --version    # confirm this resolves on your index; note the printed version
```

If `0.8.0` does not resolve, pick the version that does and use it as `DEFAULT_CBM_VERSION` in Task 2 (the repo's `../codebase-memory-mcp/server.json` says `0.7.0`; the latest git tag is `v0.8.0` — confirm what the package index actually serves).

---

## Task 1: `CBMClient` env/cwd passthrough

**Files:**
- Modify: `repo_memory/graph/client.py` (the `CBMClient.__init__`)
- Test: `tests/test_rm_deploy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rm_deploy.py` with:

```python
"""Tests for the CBM deployment/config layer (resolver + client passthrough + wiring)."""

from repo_memory.graph.client import CBMClient


def test_cbmclient_sets_env_and_cwd_on_params():
    client = CBMClient(["mybin", "--flag"], env={"CBM_CACHE_DIR": "/tmp/x"}, cwd="/repo")
    assert client._params.command == "mybin"
    assert client._params.args == ["--flag"]
    assert client._params.env == {"CBM_CACHE_DIR": "/tmp/x"}
    assert client._params.cwd == "/repo"


def test_cbmclient_env_and_cwd_default_to_none():
    client = CBMClient(["mybin"])
    assert client._params.env is None
    assert client._params.cwd is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_rm_deploy.py -p no:cacheprovider -v`
Expected: `test_cbmclient_sets_env_and_cwd_on_params` FAILS with `TypeError: __init__() got an unexpected keyword argument 'env'`.

- [ ] **Step 3: Add env/cwd to CBMClient**

In `repo_memory/graph/client.py`, replace the `__init__`:

```python
    def __init__(self, command: Optional[list[str]] = None, *, call_timeout: float = 30.0,
                 env: Optional[dict] = None, cwd: Optional[str] = None):
        cmd = command or DEFAULT_CBM_COMMAND
        # NOTE: the MCP SDK merges `env` over a clean get_default_environment(), NOT the parent
        # env. Callers must include any non-CBM_* vars CBM needs (see repo_memory.deploy.PRESERVE_ENV).
        self._params = StdioServerParameters(command=cmd[0], args=list(cmd[1:]), env=env, cwd=cwd)
        self._call_timeout = call_timeout
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_rm_deploy.py -p no:cacheprovider -v`
Expected: both tests PASS. (If `test_cbmclient_env_and_cwd_default_to_none` fails because the SDK defaults `env` to something other than `None`, change that assertion to match the SDK's documented default and note it.)

- [ ] **Step 5: Commit**

```bash
git add -f tests/test_rm_deploy.py
git add repo_memory/graph/client.py
git commit -m "feat(repo_memory): CBMClient env/cwd passthrough for deploy config"
```

---

## Task 2: `deploy.py` — resolver + profiles

**Files:**
- Create: `repo_memory/deploy.py`
- Test: `tests/test_rm_deploy.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rm_deploy.py`:

```python
import pytest

from repo_memory.deploy import (
    resolve_launch_spec, LaunchSpec, DeployConfigError, DEFAULT_CBM_VERSION,
)


def test_default_profile_is_dev_with_pinned_command():
    spec = resolve_launch_spec(environ={})
    assert isinstance(spec, LaunchSpec)
    assert spec.command == ["uvx", f"codebase-memory-mcp@{DEFAULT_CBM_VERSION}"]
    assert "CBM_CACHE_DIR" not in spec.env
    assert spec.cwd is None


def test_preserve_env_carries_through():
    spec = resolve_launch_spec(environ={"HOME": "/h", "PATH": "/b", "IGNORED": "x"})
    assert spec.env["HOME"] == "/h"
    assert spec.env["PATH"] == "/b"
    assert "IGNORED" not in spec.env


def test_raw_cbm_knob_passthrough():
    spec = resolve_launch_spec("dev", environ={"CBM_LOG_LEVEL": "debug"})
    assert spec.env["CBM_LOG_LEVEL"] == "debug"


def test_profile_env_applied():
    spec = resolve_launch_spec("ephemeral", environ={}, cache_dir="/t")
    assert spec.env["CBM_LOG_LEVEL"] == "warn"
    assert spec.env["CBM_CACHE_DIR"] == "/t"


def test_env_overrides_profile():
    spec = resolve_launch_spec("ephemeral", environ={"CBM_LOG_LEVEL": "error"}, cache_dir="/t")
    assert spec.env["CBM_LOG_LEVEL"] == "error"   # env > profile


def test_cache_dir_arg_wins_over_env():
    spec = resolve_launch_spec("ephemeral", environ={"CBM_CACHE_DIR": "/a"}, cache_dir="/b")
    assert spec.env["CBM_CACHE_DIR"] == "/b"


def test_requires_cache_dir_raises():
    with pytest.raises(DeployConfigError):
        resolve_launch_spec("ephemeral", environ={})


def test_unknown_profile_raises():
    with pytest.raises(DeployConfigError):
        resolve_launch_spec("nope", environ={})


def test_command_override_splits():
    spec = resolve_launch_spec("dev", environ={"REPO_MEMORY_CBM_COMMAND": "/opt/cbm --foo"})
    assert spec.command == ["/opt/cbm", "--foo"]


def test_version_override():
    spec = resolve_launch_spec("dev", environ={"REPO_MEMORY_CBM_VERSION": "9.9.9"})
    assert spec.command == ["uvx", "codebase-memory-mcp@9.9.9"]


def test_invalid_workers_dropped_valid_kept():
    bad = resolve_launch_spec("dev", environ={"CBM_WORKERS": "0"})
    assert "CBM_WORKERS" not in bad.env
    good = resolve_launch_spec("dev", environ={"CBM_WORKERS": "4"})
    assert good.env["CBM_WORKERS"] == "4"


def test_profile_selected_from_environ():
    spec = resolve_launch_spec(environ={"REPO_MEMORY_CBM_PROFILE": "ephemeral", "CBM_CACHE_DIR": "/t"})
    assert spec.env["CBM_CACHE_DIR"] == "/t"
    assert spec.env["CBM_LOG_LEVEL"] == "warn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_rm_deploy.py -p no:cacheprovider -v`
Expected: the new tests FAIL with `ModuleNotFoundError: No module named 'repo_memory.deploy'`.

- [ ] **Step 3: Create the resolver**

Create `repo_memory/deploy.py`:

```python
"""Resolve a CBM launch spec (command/env/cwd) per deployment profile.

Pure: reads only the `environ` passed in (defaulting to os.environ). No file IO.
This is how repo_memory injects per-deployment settings into the CBM subprocess
without forking CBM. See docs/superpowers/specs/2026-06-14-repo-memory-cbm-deploy-config-design.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_CBM_VERSION = "0.8.0"

# Vars CBM reads that the MCP SDK's clean-env merge may not carry; preserve those present.
PRESERVE_ENV = ("HOME", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA",
                "PATH", "TMP", "TEMP", "USERPROFILE")

# Raw CBM_* knobs honored if present in the environment (passed straight through, env > profile).
KNOBS = ("CBM_CACHE_DIR", "CBM_WORKERS", "CBM_LOG_LEVEL", "CBM_DIAGNOSTICS",
         "CBM_SEMANTIC_ENABLED", "CBM_SEMANTIC_THRESHOLD", "CBM_LSP_DISABLED",
         "CBM_SQLITE_MMAP_SIZE")

# Declarative per-target profiles. "requires_cache_dir" => resolve fails if none supplied.
# "version" (optional) pins a CBM version for that profile (env override still wins).
PROFILES: dict = {
    "dev": {"requires_cache_dir": False, "env": {}},
    "ephemeral": {"requires_cache_dir": True, "env": {"CBM_LOG_LEVEL": "warn"}},
    "shared": {"requires_cache_dir": True,
               "env": {"CBM_SEMANTIC_ENABLED": "1", "CBM_SQLITE_MMAP_SIZE": "1073741824"}},
    "ci": {"requires_cache_dir": True, "env": {"CBM_LOG_LEVEL": "warn"}},
}


class DeployConfigError(RuntimeError):
    """A deployment profile cannot be resolved into a runnable launch spec."""


@dataclass(frozen=True)
class LaunchSpec:
    command: list
    env: dict
    cwd: Optional[str] = None


def _command(environ: dict, profile: dict) -> list:
    override = environ.get("REPO_MEMORY_CBM_COMMAND")
    if override:
        return override.split()
    version = (environ.get("REPO_MEMORY_CBM_VERSION")
               or profile.get("version")
               or DEFAULT_CBM_VERSION)
    return ["uvx", f"codebase-memory-mcp@{version}"]


def resolve_launch_spec(profile_name: Optional[str] = None,
                        environ: Optional[dict] = None,
                        *, cache_dir: Optional[str] = None) -> LaunchSpec:
    environ = os.environ if environ is None else environ
    name = profile_name or environ.get("REPO_MEMORY_CBM_PROFILE") or "dev"
    if name not in PROFILES:
        raise DeployConfigError(
            f"unknown CBM profile '{name}'; known: {', '.join(sorted(PROFILES))}")
    profile = PROFILES[name]

    # precedence: profile env -> raw CBM_* from environ -> explicit cache_dir arg
    env: dict = dict(profile["env"])
    for knob in KNOBS:
        if knob in environ:
            env[knob] = environ[knob]
    if cache_dir is not None:
        env["CBM_CACHE_DIR"] = cache_dir

    if profile.get("requires_cache_dir") and not env.get("CBM_CACHE_DIR"):
        raise DeployConfigError(
            f"profile '{name}' requires a cache dir; set CBM_CACHE_DIR or pass cache_dir=")

    # drop an invalid worker count rather than spawn CBM with a bad value
    if "CBM_WORKERS" in env:
        try:
            n = int(env["CBM_WORKERS"])
            if not (1 <= n <= 256):
                raise ValueError
        except (ValueError, TypeError):
            env.pop("CBM_WORKERS")

    # preserve vars CBM needs that the SDK clean-env merge may drop
    for var in PRESERVE_ENV:
        if var in environ and var not in env:
            env[var] = environ[var]

    return LaunchSpec(command=_command(environ, profile), env=env,
                      cwd=environ.get("REPO_MEMORY_CBM_CWD"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_rm_deploy.py -p no:cacheprovider -v`
Expected: all Task 1 + Task 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add repo_memory/deploy.py tests/test_rm_deploy.py
git commit -m "feat(repo_memory): deploy.py launch-spec resolver + profiles"
```

---

## Task 3: `server.py` — wire the resolver into the spawn

**Files:**
- Modify: `repo_memory/server.py` (`build_app` signature + lifespan; `main()`)
- Test: `tests/test_rm_deploy.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rm_deploy.py`:

```python
def test_build_app_accepts_cbm_env_and_cwd(tmp_path):
    from repo_memory.server import build_app
    app = build_app(wiki_dir=str(tmp_path), entity_map_path=str(tmp_path / "em.json"),
                    cbm_command=["uvx", "cbm@x"], cbm_env={"CBM_CACHE_DIR": "/t"}, cbm_cwd=None)
    assert app is not None


def test_main_wires_resolved_spec_into_build_app(monkeypatch):
    import repo_memory.server as srv
    from repo_memory.deploy import LaunchSpec
    captured = {}

    class FakeApp:
        def run(self, **kw):
            captured["transport"] = kw.get("transport")

    monkeypatch.setattr(srv, "build_app", lambda **kw: (captured.update(kw) or FakeApp()))
    monkeypatch.setattr(srv, "resolve_launch_spec",
                        lambda **kw: LaunchSpec(command=["uvx", "cbm@x"],
                                                env={"CBM_CACHE_DIR": "/t"}, cwd=None))
    monkeypatch.setenv("REPO_MEMORY_WIKI_DIR", "docs")
    srv.main()

    assert captured["cbm_command"] == ["uvx", "cbm@x"]
    assert captured["cbm_env"] == {"CBM_CACHE_DIR": "/t"}
    assert captured["cbm_cwd"] is None
    assert captured["transport"] == "stdio"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_rm_deploy.py -p no:cacheprovider -v`
Expected: `test_build_app_accepts_cbm_env_and_cwd` FAILS (`unexpected keyword argument 'cbm_env'`); `test_main_wires_...` FAILS (`AttributeError: ... has no attribute 'resolve_launch_spec'`).

- [ ] **Step 3: Edit `build_app`, the lifespan, and `main()`**

In `repo_memory/server.py`, add the import near the other `repo_memory` imports:

```python
from repo_memory.deploy import resolve_launch_spec
```

Change the `build_app` signature and the `CBMClient(...)` line inside `lifespan`:

```python
def build_app(*, wiki_dir: str, entity_map_path: str,
              repo_head: Optional[str] = None,
              cbm_command: Optional[list] = None,
              cbm_env: Optional[dict] = None,
              cbm_cwd: Optional[str] = None) -> FastMCP:
    state = load_app_state(wiki_dir=wiki_dir, entity_map_path=entity_map_path,
                           repo_head=repo_head)

    @asynccontextmanager
    async def lifespan(_app):
        client = CBMClient(cbm_command, env=cbm_env, cwd=cbm_cwd)
        try:
            await client.start()
            state.cbm = client
        except Exception:
            state.cbm = None  # degrade: wiki tools still work
        try:
            yield {}
        finally:
            await client.aclose()
```

Replace `main()`:

```python
def main() -> None:
    wiki_dir = os.environ.get("REPO_MEMORY_WIKI_DIR", "docs")
    entity_map_path = os.environ.get("REPO_MEMORY_ENTITY_MAP", "entity_map.json")
    spec = resolve_launch_spec(environ=os.environ)
    build_app(wiki_dir=wiki_dir, entity_map_path=entity_map_path,
              cbm_command=spec.command, cbm_env=spec.env,
              cbm_cwd=spec.cwd).run(transport="stdio")
```

(Remove the old `# pragma: no cover` comment on `main()` if present — it is now exercised by a test.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_rm_deploy.py -p no:cacheprovider -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add repo_memory/server.py tests/test_rm_deploy.py
git commit -m "feat(repo_memory): resolve a deploy profile and inject CBM env at spawn"
```

---

## Task 4: Deploy recipes doc

**Files:**
- Create: `docs/repo_memory-deploy.md`

- [ ] **Step 1: Write the doc**

Create `docs/repo_memory-deploy.md`:

````markdown
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
  REPO_MEMORY_CBM_VERSION: "0.8.0"
  CBM_CACHE_DIR: ".cbm-cache"
steps:
  - uses: actions/cache@v4
    with:
      path: .cbm-cache
      key: cbm-${{ hashFiles('**/*.py') }}
  - run: <run repo_memory tasks>
```

> Confirm `uvx codebase-memory-mcp@<version>` resolves on your package index before pinning. As of this
> writing the repo's `server.json` says `0.7.0` while the latest tag is `v0.8.0`.
````

- [ ] **Step 2: Sanity-check the doc references real profiles/vars**

Run: `grep -oE '"(dev|ephemeral|shared|ci)"' repo_memory/deploy.py | sort -u`
Expected: all four profile names appear (the doc's profile table must match these).

- [ ] **Step 3: Commit**

```bash
git add docs/repo_memory-deploy.md
git commit -m "docs(repo_memory): CBM deployment profiles + recipes"
```

---

## Task 5: Gated integration test (real CBM, cache-dir isolation)

**Files:**
- Test: `tests/test_rm_deploy.py`

This proves env injection works end to end: CBM started under an injected `CBM_CACHE_DIR` writes its
index there. It is **gated** (`@pytest.mark.integration`) — it needs `uvx` + the CBM package and is
skipped in the normal offline suite.

- [ ] **Step 1: Add the gated test**

Append to `tests/test_rm_deploy.py`:

```python
import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_injected_cache_dir_is_used(tmp_path):
    """CBM started via the resolved spec writes its index under the injected CBM_CACHE_DIR."""
    from repo_memory.graph.client import CBMClient
    from repo_memory.deploy import resolve_launch_spec

    # a tiny repo to index
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def hello():\n    return 1\n")

    cache = tmp_path / "cbm-cache"
    spec = resolve_launch_spec("ephemeral", environ=dict(os.environ), cache_dir=str(cache))

    client = CBMClient(spec.command, env=spec.env, cwd=spec.cwd)
    await client.start()
    try:
        await client.call_tool_with_restart("index_repository", {"repo_path": str(repo)})
    finally:
        await client.aclose()

    # CBM created its store under the injected cache dir, not the default ~/.cache location
    assert cache.exists()
    assert any(cache.rglob("*")), "expected CBM to write its index under the injected CBM_CACHE_DIR"
```

Add `import os` at the top of the file if not already present from Task 2 (it is imported indirectly
via tests, but add an explicit `import os` to be safe).

- [ ] **Step 2: Run it (gated, manual)**

Run: `.venv/bin/python -m pytest tests/test_rm_deploy.py -p no:cacheprovider -m integration -v`
Expected: PASS when `uvx` + CBM are available and network allows the first `uvx` fetch. If CBM is not
installed, this test is the only one selected by `-m integration`; it will error on spawn — that is
expected in environments without CBM, which is why it is gated out of the default suite.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rm_deploy.py
git commit -m "test(repo_memory): gated integration test for injected CBM_CACHE_DIR"
```

---

## Task 6: Regression — full offline suite

- [ ] **Step 1: Run the whole offline suite (integration deselected)**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider -m "not integration"`
Expected: all tests PASS (existing `test_rm_*` + the new `test_rm_deploy.py` offline tests). If
`pytest-cov` is not installed, append `--no-cov`.

- [ ] **Step 2: Lint / type-check the new + changed files**

```bash
.venv/bin/ruff check repo_memory/deploy.py repo_memory/graph/client.py repo_memory/server.py
.venv/bin/black --check repo_memory/deploy.py repo_memory/graph/client.py repo_memory/server.py
.venv/bin/mypy repo_memory/deploy.py
```
Expected: clean (line-length 100, py312 per pyproject). Fix any findings, then re-run.

- [ ] **Step 3: Final commit (only if Step 2 made changes)**

```bash
git add repo_memory/ tests/test_rm_deploy.py
git commit -m "chore(repo_memory): lint/format deploy layer"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** §3 components → `deploy.py` (Task 2), `client.py` (Task 1), `server.py` (Task 3),
  `test_rm_deploy.py` (Tasks 1/2/3/5), `docs/repo_memory-deploy.md` (Task 4). §4 resolver +
  precedence + `requires_cache_dir` + worker validation → Task 2 tests. §5 client passthrough +
  clean-env note → Task 1. §6 wiring → Task 3. §7 error handling (unwritable/missing cache dir →
  `DeployConfigError`; invalid workers dropped) → Task 2. §8 testing (unit + gated integration) →
  Tasks 2 & 5. §9 phases (a–e) → Tasks 1–5. §11 version-pin risk → Task 0 Step 3. §12 coordination →
  Task 0. **Note:** §7 "fail fast on *unwritable* cache dir" is implemented as fail-fast on a
  *missing required* cache dir (a write-permission probe was deemed out of scope; CBM itself errors on
  an unwritable dir at spawn). All other requirements have a task.
- **Placeholder scan:** none — every code step shows complete code; every command states its expected
  outcome. The only conditional ("if a signature drifted", "if the SDK env default differs") gives the
  concrete adaptation.
- **Type/name consistency:** `LaunchSpec(command, env, cwd)`, `resolve_launch_spec(profile_name,
  environ, *, cache_dir)`, `DeployConfigError`, `DEFAULT_CBM_VERSION`, `PROFILES`, `PRESERVE_ENV`,
  `KNOBS`, and `build_app(..., cbm_env, cbm_cwd)` / `CBMClient(..., env, cwd)` are used identically
  across Tasks 1–5.
````
