# Adoption Hook — Productize the Gated Nudge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the lap-9 `assisted` mechanism (an insufficiency-gated soft nudge, 53%) as a real Claude Code `UserPromptSubmit` hook, so a live agent in a user's repo is nudged to call `find_related` when the needed helper is out of its local work-tree.

**Architecture:** Lift the gate + nudge out of `eval/` into a shared `repo_atlas/adoption.py` (the eval delegates to it — DRY). Add a fail-open `repo-atlas gate` CLI the hook shells out to (intent pre-filter → `find_related` across all repos → print the nudge iff the top hit is out-of-work-tree). Document an opt-in `UserPromptSubmit` config.

**Tech Stack:** Python 3.12, pytest 9.0.3 (`--no-cov`), `repo_atlas` (`cli.py`, `retrieve.py`, `eval/offline/retriever.py`), Claude Code hooks.

**Conventions:** Work in the worktree `/mnt/x/code/knowledgeLoop/.claude/worktrees/cm`; venv `.venv/bin/python`. Run new/changed unit tests **per-file** (`-p no:cacheprovider --no-cov`). `tests/` is gitignored → `git add -f` new test files.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `repo_atlas/adoption.py` | **create** | shared gate + nudge: `NUDGE`, `_present_in_tree`, `gate_query_out_of_tree`, `nudge_for`, `is_coding_intent` |
| `repo_atlas/eval/adoption.py` | modify | thin delegator/re-export (Task→query) so eval imports stay stable |
| `repo_atlas/eval/runner.py` | modify | import `NUDGE` from `repo_atlas.adoption` instead of defining it |
| `repo_atlas/cli.py` | modify | `repo-atlas gate` subcommand (`_run_gate`, `_gate_retriever`) |
| `docs/applying-to-a-new-repo.md` | modify | opt-in `UserPromptSubmit` hook config + prereqs |
| `tests/test_adoption.py` | **create** | gate + nudge + intent tests |
| `tests/test_cli_gate.py` | **create** | `gate` CLI: pre-filter short-circuit, fail-open, happy path |

---

## Task 1: Shared gate + nudge in `repo_atlas/adoption.py` (eval delegates)

**Files:** Create `repo_atlas/adoption.py`; Modify `repo_atlas/eval/adoption.py`, `repo_atlas/eval/runner.py`; Test `tests/test_adoption.py`.

- [ ] **Step 1: Write the failing test** — create `tests/test_adoption.py`:

```python
import pytest
from repo_atlas.adoption import (NUDGE, _present_in_tree, gate_query_out_of_tree, nudge_for)
from repo_atlas.eval.offline.retriever import StubRetriever


def test_present_in_tree_basename_and_skips_git(tmp_path):
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    assert _present_in_tree("modules/ocl/cl_demo_handler.cpp", str(tmp_path)) is True
    assert _present_in_tree("xcore/vec_mat.h", str(tmp_path)) is False
    gd = tmp_path / ".git"; gd.mkdir(); (gd / "vec_mat.h").write_text("x")
    assert _present_in_tree("vec_mat.h", str(tmp_path)) is False        # .git is skipped


@pytest.mark.asyncio
async def test_gate_true_when_top_hit_out_of_tree(tmp_path):
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    sr = StubRetriever(hits_by_query={"q": [{"name": "slerp", "file": "xcore/vec_mat.h", "text": ""}]})
    assert await gate_query_out_of_tree("q", str(tmp_path), sr) is True


@pytest.mark.asyncio
async def test_gate_false_when_in_tree_or_empty_or_no_retriever(tmp_path):
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    in_tree = StubRetriever(hits_by_query={"q": [{"name": "f", "file": "ocl/cl_demo_handler.cpp", "text": ""}]})
    assert await gate_query_out_of_tree("q", str(tmp_path), in_tree) is False
    assert await gate_query_out_of_tree("q", str(tmp_path), StubRetriever()) is False    # no hits
    assert await gate_query_out_of_tree("q", str(tmp_path), None) is False               # no retriever


@pytest.mark.asyncio
async def test_nudge_for_returns_text_iff_out_of_tree(tmp_path):
    (tmp_path / "local.cpp").write_text("x")
    out = StubRetriever(hits_by_query={"q": [{"name": "h", "file": "other/x.h", "text": ""}]})
    assert await nudge_for("q", str(tmp_path), out) == NUDGE
    inn = StubRetriever(hits_by_query={"q": [{"name": "h", "file": "local.cpp", "text": ""}]})
    assert await nudge_for("q", str(tmp_path), inn) is None
```

- [ ] **Step 2: Run, verify it FAILS** — `ImportError: No module named 'repo_atlas.adoption'`.

Run: `.venv/bin/python -m pytest tests/test_adoption.py -p no:cacheprovider --no-cov -q`

- [ ] **Step 3: Implement** — create `repo_atlas/adoption.py`:

```python
"""Adoption gate + nudge — the productized `assisted` mechanism, shared by the eval and the
`repo-atlas gate` hook. Answer-agnostic: it asks only "is the most-relevant thing for this prompt
absent from the local work-tree?" (i.e. plausibly in a related repo)."""
from __future__ import annotations

import os

# Soft, conditional nudge injected when the gate fires. NOT imperative (no "MUST"/"FIRST" — that is
# the mandatory STEER): it suggests the cross-repo tool when local search comes up empty.
NUDGE = (
    "Note: this task may depend on a helper or convention that is NOT present in your local "
    "files — it may live in a related repository. If your own search of this codebase does not "
    "surface one, consider calling mcp__repo-atlas__find_related to look across related repos "
    "before implementing it yourself.\n\nTask:\n"
)


def _present_in_tree(rel_or_name: str, work_dir: str) -> bool:
    """True iff a file with the same basename as `rel_or_name` exists anywhere under `work_dir`
    (skipping `.git`). Basename match: retrieval paths are repo-relative and won't line up with the
    work-tree's layout."""
    target = os.path.basename(rel_or_name)
    if not target:
        return False
    for _root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        if target in files:
            return True
    return False


async def gate_query_out_of_tree(query: str, work_dir: str, retriever, *, k: int = 5) -> bool:
    """True iff the top all-repos retrieval hit for `query` lives in a file ABSENT from `work_dir`.
    False when no retriever, no hits, or the top hit is in-tree."""
    if retriever is None:
        return False
    units = await retriever.retrieve(query, None, k)
    if not units:
        return False
    f = units[0].get("file") or units[0].get("path") or ""
    return bool(f) and not _present_in_tree(f, work_dir)


async def nudge_for(prompt: str, work_dir: str, retriever, *, k: int = 5) -> str | None:
    """Return the NUDGE text iff the gate judges the prompt's need to be out of the local work-tree."""
    return NUDGE if await gate_query_out_of_tree(prompt, work_dir, retriever, k=k) else None
```

Then rewrite `repo_atlas/eval/adoption.py` to delegate (keeps eval import paths stable):

```python
"""Eval-facing adoption gate: delegates to the shared product gate in `repo_atlas.adoption`,
mapping a Task to its focused retrieval query. Thin wrapper so eval imports stay stable."""
from __future__ import annotations

from repo_atlas.adoption import _present_in_tree, gate_query_out_of_tree  # noqa: F401  (re-export)
from repo_atlas.eval.tasks import task_query


async def local_context_insufficient(task, work_dir, retriever, *, k: int = 5) -> bool:
    """True iff the task's needed helper is out of the local work-tree (uses the task's focused
    retrieval_query). Thin wrapper over repo_atlas.adoption.gate_query_out_of_tree."""
    return await gate_query_out_of_tree(task_query(task), work_dir, retriever, k=k)
```

Then in `repo_atlas/eval/runner.py`: delete the `NUDGE = ( ... )` block (and its preceding comment), and add to the imports near the top: `from repo_atlas.adoption import NUDGE`. (`runner.NUDGE` stays importable for `tests/test_eval_runner.py`.)

- [ ] **Step 4: Run, verify PASSES** — the new file plus the two eval files it touches:

```
.venv/bin/python -m pytest tests/test_adoption.py tests/test_eval_adoption.py tests/test_eval_runner.py -p no:cacheprovider --no-cov -q
.venv/bin/ruff check repo_atlas/adoption.py repo_atlas/eval/adoption.py repo_atlas/eval/runner.py
```
Expected: all pass; ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
git add repo_atlas/adoption.py repo_atlas/eval/adoption.py repo_atlas/eval/runner.py
git add -f tests/test_adoption.py
git commit -m "feat(repo_atlas): shared adoption gate+nudge in repo_atlas/adoption.py (eval delegates)"
```

---

## Task 2: `is_coding_intent` pre-filter

**Files:** Modify `repo_atlas/adoption.py`; Test `tests/test_adoption.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_adoption.py`:

```python
from repo_atlas.adoption import is_coding_intent


def test_is_coding_intent_true_for_implementation_requests():
    for p in ["Implement a sepia filter", "add per-handler FPS logging",
              "fix the codec crash", "use the existing profiling helper", "refactor the blender"]:
        assert is_coding_intent(p) is True


def test_is_coding_intent_false_for_questions_and_blank():
    for p in ["What does this function do?", "explain the architecture", "", "summarize the module"]:
        assert is_coding_intent(p) is False
```

- [ ] **Step 2: Run, verify it FAILS** — `ImportError: cannot import name 'is_coding_intent'`.

Run: `.venv/bin/python -m pytest tests/test_adoption.py -p no:cacheprovider --no-cov -q -k coding_intent`

- [ ] **Step 3: Implement** — add to `repo_atlas/adoption.py` (after the imports, before `_present_in_tree`; add `import re` to the imports):

```python
import re

_CODING_INTENT = re.compile(
    r"\b(implement|add|fix|use the existing|wire up|refactor|create|write|hook up|"
    r"call the|integrate|support)\b", re.IGNORECASE)


def is_coding_intent(prompt: str) -> bool:
    """Cheap pre-filter: does the prompt look like an implementation/change request? Keeps the gate
    from running a retrieval on Q&A / explanation prompts."""
    return bool(_CODING_INTENT.search(prompt or ""))
```

- [ ] **Step 4: Run, verify PASSES**

```
.venv/bin/python -m pytest tests/test_adoption.py -p no:cacheprovider --no-cov -q
.venv/bin/ruff check repo_atlas/adoption.py
```

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/adoption.py tests/test_adoption.py
git commit -m "feat(repo_atlas/adoption): is_coding_intent pre-filter for the gate"
```

---

## Task 3: `repo-atlas gate` CLI (fail-open hook entrypoint)

**Files:** Modify `repo_atlas/cli.py`; Test `tests/test_cli_gate.py`.

- [ ] **Step 1: Write the failing test** — create `tests/test_cli_gate.py`:

```python
import os
from repo_atlas import cli
from repo_atlas.adoption import NUDGE
from repo_atlas.eval.offline.retriever import StubRetriever


def test_gate_parser():
    args = cli.build_parser().parse_args(["gate", "--prompt", "add X", "--k", "7"])
    assert args.cmd == "gate" and args.prompt == "add X" and args.k == 7


def test_gate_skips_non_coding_prompt(capsys, monkeypatch):
    # pre-filter short-circuits: no retriever is ever built, nothing printed, exit 0
    def _boom():
        raise AssertionError("retriever must not be built for a non-coding prompt")
    monkeypatch.setattr(cli, "_gate_retriever", _boom)
    rc = cli.main(["gate", "--prompt", "what does this function do?"])
    assert rc == 0 and capsys.readouterr().out == ""


def test_gate_fail_open_on_retriever_error(capsys, monkeypatch):
    def _boom():
        raise RuntimeError("no index / server down")
    monkeypatch.setattr(cli, "_gate_retriever", _boom)
    rc = cli.main(["gate", "--prompt", "implement a sepia filter"])
    assert rc == 0 and capsys.readouterr().out == ""        # fail-open: swallow, print nothing


def test_gate_prints_nudge_when_out_of_tree(capsys, monkeypatch, tmp_path):
    (tmp_path / "local.cpp").write_text("x")
    monkeypatch.chdir(tmp_path)
    sr = StubRetriever(hits_by_query={"implement X using the existing helper":
                                      [{"name": "h", "file": "other/x.h", "text": ""}]})
    monkeypatch.setattr(cli, "_gate_retriever", lambda: sr)
    rc = cli.main(["gate", "--prompt", "implement X using the existing helper"])
    assert rc == 0 and capsys.readouterr().out == NUDGE


def test_gate_silent_when_in_tree(capsys, monkeypatch, tmp_path):
    (tmp_path / "local.cpp").write_text("x")
    monkeypatch.chdir(tmp_path)
    sr = StubRetriever(hits_by_query={"implement X using the existing helper":
                                      [{"name": "h", "file": "local.cpp", "text": ""}]})
    monkeypatch.setattr(cli, "_gate_retriever", lambda: sr)
    rc = cli.main(["gate", "--prompt", "implement X using the existing helper"])
    assert rc == 0 and capsys.readouterr().out == ""
```

- [ ] **Step 2: Run, verify it FAILS** — no `gate` subcommand / no `_gate_retriever`.

Run: `.venv/bin/python -m pytest tests/test_cli_gate.py -p no:cacheprovider --no-cov -q`

- [ ] **Step 3: Implement** — in `repo_atlas/cli.py`:

(a) In `build_parser()`, after the `eval-arms` parser block (before `return p`):

```python
    ga = sub.add_parser("gate",
                        help="UserPromptSubmit hook: print a cross-repo nudge iff the prompt's need "
                             "is out of the local work-tree (fail-open)")
    ga.add_argument("--prompt", help="prompt text (testing); default reads the hook JSON on stdin")
    ga.add_argument("--k", type=int, default=5, help="gate retrieval depth (default 5)")
```

(b) Add a monkeypatchable retriever builder + the command, near the other `_run_*` functions:

```python
def _gate_retriever():
    """Build the production retriever from config (separate fn so tests can monkeypatch it)."""
    from repo_atlas.config import load_config
    from repo_atlas.store import Store
    from repo_atlas.embed import GatewayEmbedder
    from repo_atlas.eval.offline.retriever import OfflineRetriever
    cfg = load_config(os.environ)
    return OfflineRetriever(Store(cfg.db_path),
                            GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model))


def _run_gate(args) -> int:
    """Print a cross-repo nudge to stdout iff the gate fires. FAIL-OPEN: any error -> no output,
    exit 0 (a prompt-path hook must never disrupt the session)."""
    import sys
    try:
        import asyncio
        import json
        from repo_atlas.adoption import is_coding_intent, nudge_for
        prompt, work_dir = args.prompt, os.getcwd()
        if prompt is None:                                  # hook path: JSON payload on stdin
            raw = sys.stdin.read()
            data = json.loads(raw) if raw.strip().startswith("{") else {}
            prompt = data.get("prompt", "")
            work_dir = data.get("cwd") or work_dir
        if not prompt or not is_coding_intent(prompt):
            return 0
        nudge = asyncio.run(nudge_for(prompt, work_dir, _gate_retriever(), k=args.k))
        if nudge:
            sys.stdout.write(nudge)
    except Exception:                                       # noqa: BLE001 - fail-open boundary
        pass
    return 0
```

(c) In `main()`, add the dispatch (before the default `serve` fallthrough):

```python
    if args.cmd == "gate":
        return _run_gate(args)
```

Ensure `import os` is present at the top of `cli.py` (it already is).

- [ ] **Step 4: Run, verify PASSES**

```
.venv/bin/python -m pytest tests/test_cli_gate.py tests/test_eval_cli.py -p no:cacheprovider --no-cov -q
.venv/bin/ruff check repo_atlas/cli.py
```

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/cli.py
git add -f tests/test_cli_gate.py
git commit -m "feat(repo_atlas/cli): repo-atlas gate — fail-open UserPromptSubmit hook entrypoint"
```

---

## Task 4: Document the opt-in hook (no code)

**Files:** Modify `docs/applying-to-a-new-repo.md`.

- [ ] **Step 1: Verify the Claude Code hook contract**

Confirm against current Claude Code docs (or `claude` help) that a `UserPromptSubmit` hook (1) receives a JSON payload on stdin containing at least `prompt` and `cwd`, and (2) treats a command hook's **stdout (with exit 0) as additional context** injected into the turn. Note the verified shape; if a key name differs, adjust `_run_gate`'s `data.get(...)` accordingly (the `--prompt` flag and the fail-open wrapper keep the CLI working regardless).

- [ ] **Step 2: Add an "Adoption nudge (optional)" subsection** to `docs/applying-to-a-new-repo.md`, after the repo-atlas MCP-server setup, containing:

  - **Prereqs:** repos indexed (`repo-atlas index --all`) and the embeddings endpoint reachable; otherwise the hook silently no-ops. The hook **complements** the `find_related` MCP server (the nudge tells the agent to call that tool).
  - **Config** for the user's `.claude/settings.json`:

    ```json
    {
      "hooks": {
        "UserPromptSubmit": [
          { "hooks": [ { "type": "command", "command": "repo-atlas gate" } ] }
        ]
      }
    }
    ```

  - **What it does:** on each implementation-style prompt, runs the insufficiency gate (`find_related` across all registered repos); if the most-relevant prior art lives outside the current repo, injects a one-line nudge so the agent reaches for `find_related`. Fail-open (never blocks a prompt).
  - **Test it:** `printf '{"prompt":"implement X using the existing helper","cwd":"'"$PWD"'"}' | repo-atlas gate` prints the nudge for a cross-repo need and nothing for a local one; `repo-atlas gate --prompt "..."` is the ad-hoc form that surfaces errors (the hook path swallows them).

- [ ] **Step 3: Commit**

```bash
git add docs/applying-to-a-new-repo.md
git commit -m "docs: opt-in UserPromptSubmit adoption-nudge hook (repo-atlas gate)"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (shared `adoption.py`: NUDGE, _present_in_tree, gate_query_out_of_tree, nudge_for; eval delegates) → Task 1. `is_coding_intent` → Task 2. ✓
- Component 2 (`repo-atlas gate` CLI: stdin JSON, pre-filter, fail-open) → Task 3. ✓
- Component 3 (hook config + docs + prereqs + test) → Task 4. ✓
- Non-goals honored: nudge-only (no auto-inject), `UserPromptSubmit` only, reuse `find_related` via `OfflineRetriever`, opt-in docs, no re-validation eval. ✓
- Error handling (fail-open) → Task 3 (`_run_gate` try/except → exit 0) + tests. ✓
- Risk "hook contract drift" → Task 4 Step 1 (verify) + the `--prompt` testable seam. ✓

**Placeholder scan:** none — every code step is complete; commands are concrete.

**Type consistency:** `gate_query_out_of_tree(query, work_dir, retriever, *, k=5)`, `nudge_for(prompt, work_dir, retriever, *, k=5)`, `is_coding_intent(prompt)`, `_run_gate(args)`, `_gate_retriever()` are used identically across tasks. `eval/adoption.local_context_insufficient(task, work_dir, retriever, *, k=5)` keeps its existing signature (delegates). `StubRetriever(hits_by_query=...)` and its `.retrieve(query, repos, k)` match `repo_atlas/eval/offline/retriever.py`. The eval re-export keeps `tests/test_eval_adoption.py` (imports `local_context_insufficient`, `_present_in_tree`) and `tests/test_eval_runner.py` (imports `NUDGE`) green.
