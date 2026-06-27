# Adoption Measurement — Session-Limit-Safe Eval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a Claude session-limit hit stop the agentic eval cleanly (never scored as a task failure), then measure whether the existing gated `assisted` nudge captures the lap-8 cross-repo ceiling.

**Architecture:** Three small, TDD'd changes to the existing eval harness — a pure `_is_session_limit()` classifier, a `SessionLimitReached` exception raised at the `claude -p` I/O boundary, and a special-case in `run_multi_eval` that stops cleanly and aggregates only the tasks that did real work — followed by a runbook that runs the adoption arms on the N=15 cross-repo set and reads `assisted_lift`.

**Tech Stack:** Python 3.12, pytest 9.0.3 (`--no-cov` or install pytest-cov), `repo_atlas/eval/` harness, `scripts/run_eval_arms.sh`, the bge-m3 server (`:11500`) + the two cross-repo substrates (`/home/vinc/repo-atlas-xrepo`, `/home/vinc/repo-atlas-xrepo2`).

**Conventions:** Work in the worktree `/mnt/x/code/knowledgeLoop/.claude/worktrees/cm`; use its venv (`.venv/bin/python`). `tests/` is gitignored → `git add -f` any new test file (here we only modify existing test files, so plain `git add` works). Run new/changed unit tests **per-file**.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `repo_atlas/eval/runner.py` | modify | add `_is_session_limit`, `SessionLimitReached`; raise from `_run_agent` |
| `repo_atlas/eval/harness.py` | modify | `run_multi_eval` stops clean on `SessionLimitReached` |
| `tests/test_eval_runner.py` | modify | unit tests for the classifier + `_run_agent` raising |
| `tests/test_eval_harness.py` | modify | unit test for clean stop + partial-task exclusion |

No new modules (YAGNI). No changes to the legacy `run_eval`/`run_pair` path, `RunResult`, `TaskScore`, or `aggregate`.

---

## Task 1: `_is_session_limit` classifier + `SessionLimitReached` exception

**Files:**
- Modify: `repo_atlas/eval/runner.py` (add near the top-level helpers, after the `ARMS` dict / before `class ClaudeRunner`)
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_eval_runner.py` (extend the existing import line and append the test):

```python
# extend the existing import at the top of the file:
from repo_atlas.eval.runner import (RunResult, StubRunner, ClaudeRunner, NUDGE,
                                    SessionLimitReached, _is_session_limit,
                                    _count_atlas_in_transcript, format_injection)


def test_is_session_limit_matches_quota_messages():
    assert _is_session_limit("You've hit your session limit · resets 8pm (Asia/Shanghai)") is True
    assert _is_session_limit("Claude usage limit reached") is True
    assert _is_session_limit("SESSION LIMIT") is True                      # case-insensitive


def test_is_session_limit_ignores_normal_output():
    assert _is_session_limit('{"result":"done","is_error":false,"num_turns":7}') is False
    assert _is_session_limit("I changed the buffer rate of the encoder.") is False
    assert _is_session_limit("") is False
    assert _is_session_limit(None) is False                                # tolerates None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -p no:cacheprovider --no-cov -q`
Expected: FAIL at collection — `ImportError: cannot import name 'SessionLimitReached'` (and `_is_session_limit`).

- [ ] **Step 3: Write minimal implementation**

In `repo_atlas/eval/runner.py`, add after the `ARMS = {...}` dict (around line 58) and before `class ClaudeRunner`:

```python
class SessionLimitReached(Exception):
    """The `claude` CLI reported the subscription session/usage limit. Distinct from an ordinary
    run failure: once it fires, every subsequent run also fails, so the eval must STOP cleanly
    rather than score the limit message as a grounded-success failure."""


# Substrings (lowercased) that mark a Claude quota/limit message in the CLI output.
_SESSION_LIMIT_PHRASES = (
    "hit your session limit", "session limit", "usage limit", "limit · resets", "limit reached",
)


def _is_session_limit(text) -> bool:
    """True iff `text` contains a known Claude session/usage-limit phrase (case-insensitive)."""
    t = (text or "").lower()
    return any(p in t for p in _SESSION_LIMIT_PHRASES)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -p no:cacheprovider --no-cov -q`
Expected: PASS (all tests in the file, including the two new ones).

- [ ] **Step 5: Commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
git add repo_atlas/eval/runner.py tests/test_eval_runner.py
git commit -m "feat(repo_atlas/eval): _is_session_limit classifier + SessionLimitReached"
```

---

## Task 2: `_run_agent` raises `SessionLimitReached` on a quota hit

**Files:**
- Modify: `repo_atlas/eval/runner.py` — `ClaudeRunner._run_agent` (the method added in the lap-8 timeout fix; currently: try `subprocess.run(..., timeout=self._timeout)` / except `TimeoutExpired` → `{}` / else parse JSON)
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_eval_runner.py`:

```python
import pytest as _pytest  # already imported at top as `pytest`; this alias is illustrative only


def test_run_agent_raises_on_session_limit():
    # claude prints the limit text instead of a JSON envelope -> must raise (abort), not return {}
    r = ClaudeRunner({"g": "/x"}, "/m", timeout=10)
    with pytest.raises(SessionLimitReached):
        r._run_agent(["printf", "You have hit your session limit; resets 8pm"], "/tmp")


def test_run_agent_timeout_still_returns_empty():
    # a TIMEOUT remains an ordinary per-arm failure ({}), NOT a session-limit abort
    r = ClaudeRunner({"g": "/x"}, "/m", timeout=1)
    assert r._run_agent(["sleep", "5"], "/tmp") == {}


def test_run_agent_still_parses_json():
    r = ClaudeRunner({"g": "/x"}, "/m", timeout=10)
    assert r._run_agent(["printf", '{"session_id":"abc","num_turns":3}'], "/tmp") == {
        "session_id": "abc", "num_turns": 3}
```

(The last two assert the unchanged behaviour still holds; if equivalent tests already exist in the
file, keep one copy — do not duplicate.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -p no:cacheprovider --no-cov -q -k run_agent`
Expected: `test_run_agent_raises_on_session_limit` FAILS — `_run_agent` currently returns `{}` (the limit text is not `{`-prefixed JSON), so no exception is raised.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `ClaudeRunner._run_agent` in `repo_atlas/eval/runner.py` with:

```python
    def _run_agent(self, cmd: list, work: str) -> dict:
        """Invoke `claude -p`, returning the parsed JSON envelope. A TIMEOUT returns {} (an
        ordinary per-arm failure). A SESSION-LIMIT message raises SessionLimitReached so the whole
        eval stops cleanly instead of scoring the limit as a grounded-success failure."""
        try:
            proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True,
                                  timeout=self._timeout)
        except subprocess.TimeoutExpired:
            return {}
        if _is_session_limit(proc.stdout) or _is_session_limit(proc.stderr):
            raise SessionLimitReached((proc.stdout or proc.stderr or "").strip()[:200])
        return json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -p no:cacheprovider --no-cov -q`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/runner.py tests/test_eval_runner.py
git commit -m "feat(repo_atlas/eval): _run_agent raises SessionLimitReached on a quota hit"
```

---

## Task 3: `run_multi_eval` stops cleanly on `SessionLimitReached`

**Files:**
- Modify: `repo_atlas/eval/harness.py` — `run_multi_eval` (currently: `for t in tasks: try: per_task[t.id] = await run_arms(...) except Exception: print(skip)`)
- Test: `tests/test_eval_harness.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_eval_harness.py`:

```python
import pytest
from repo_atlas.eval.runner import RunResult, SessionLimitReached
from repo_atlas.eval.harness import run_multi_eval
from repo_atlas.eval.tasks import Task


class _LimitRunner:
    """Raises SessionLimitReached when it reaches (limit_task, limit_arm); else a valid empty run."""
    def __init__(self, limit_task, limit_arm):
        self._lt, self._la = limit_task, limit_arm

    async def run(self, task, *, condition):
        if task.id == self._lt and condition == self._la:
            raise SessionLimitReached("you've hit your session limit")
        return RunResult(condition, diff="")           # valid run, empty diff -> scorer fails


class _FalseJudge:
    async def score(self, task, run):
        return False


@pytest.mark.asyncio
async def test_run_multi_eval_stops_clean_on_session_limit():
    tasks = [Task(id=f"t{i}", kind="dev", repo="r", prompt="p", rubric="x") for i in range(3)]
    runner = _LimitRunner(limit_task="t1", limit_arm="forced-inject")   # 2nd arm of the 2nd task
    sc = await run_multi_eval(tasks, runner, ["control", "forced-inject"], _FalseJudge(),
                              exists_fn=lambda s: False)
    # t0 fully completed; t1 hit the limit on its 2nd arm -> dropped; t2 never ran
    assert set(sc.per_task.keys()) == {"t0"}
    assert sc.summary["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -p no:cacheprovider --no-cov -q -k session_limit`
Expected: FAIL — the current `except Exception` swallows `SessionLimitReached`, so the loop continues; `per_task` ends up `{"t0","t2"}` (t1 skipped, t2 still ran) and `n == 2`.

- [ ] **Step 3: Write minimal implementation**

Replace `run_multi_eval` in `repo_atlas/eval/harness.py` with:

```python
async def run_multi_eval(tasks, runner, arms, judge, exists_fn: Callable[[str], bool]):
    """Multi-arm agentic eval. An ordinary task failure is skipped (logged) so one bad run doesn't
    waste a long eval. A SessionLimitReached STOPS the eval cleanly — the quota is exhausted, so
    every later run would also fail; we aggregate only the tasks that completed before it and report
    where to resume. Returns a MultiScorecard."""
    from repo_atlas.eval.aggregate import aggregate_arms
    from repo_atlas.eval.runner import SessionLimitReached
    per_task = {}
    for t in tasks:
        try:
            per_task[t.id] = await run_arms(t, runner, arms, judge, exists_fn)
        except SessionLimitReached as exc:
            done = len(per_task)
            print(f"[eval] session limit reached on task {t.id} — stopping after {done} clean "
                  f"tasks; resume the remaining {len(tasks) - done} next window: {exc}")
            break
        except Exception as exc:                       # noqa: BLE001 - resilience boundary
            print(f"[eval] task {t.id} failed, skipping: {type(exc).__name__}: {exc}")
    return aggregate_arms(per_task, arms)
```

(`Callable` is already imported at the top of `harness.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -p no:cacheprovider --no-cov -q`
Expected: PASS (whole file — the existing 4 tests plus the new one).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/harness.py tests/test_eval_harness.py
git commit -m "feat(repo_atlas/eval): run_multi_eval stops clean on SessionLimitReached"
```

---

## Task 4: Run the adoption measurement (runbook)

Not TDD — this executes the measurement the harness fix unblocks. Run it only after Tasks 1–3 are green.

**Preconditions (verify, do not assume):**
```bash
command -v claude && claude --version                       # the agent under test (Sonnet 4.6)
curl -sf -m 8 -X POST http://127.0.0.1:11500/v1/embeddings \
  -H 'content-type: application/json' -d '{"input":["x"],"model":"bge-m3"}' >/dev/null && echo BGE_UP
ls /home/vinc/repo-atlas-xrepo/atlas-xrepo.db /home/vinc/repo-atlas-xrepo2/atlas-xrepo2.db   # substrates
```
If the bge server is down, restart it:
`nohup /home/vinc/bge-m3/.venv/bin/python /home/vinc/repo-atlas-eval-full/bge_embed_server.py 11500 >/home/vinc/repo-atlas-eval-full/bge_server.log 2>&1 &`

- [ ] **Step 1: Build the N=15 ceiling-subset task dirs** (the non-guessable tasks used for the lap-8 ceiling)

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
AL=/home/vinc/repo-atlas-xrepo/adopt-libxcam;  AG=/home/vinc/repo-atlas-xrepo2/adopt-gpuimage
rm -rf "$AL" "$AG"; mkdir -p "$AL" "$AG"
for t in xr-ocl-warp-create-quaternion xr-ocl-retinex-interp4 xr-ocl-tonemap-interp2 \
         xr-ocl-fps-logging xr-ocl-gauss-table xr-ocl-scaler-double-equal \
         xr-ocl-demo-timestamp-seconds xr-ocl-vbuf-external-wrap \
         xr-ocl-fisheye-rotation-axis xr-ocl-handler-dump-data-buf; do
  cp "repo_atlas/eval/tasks-xrepo/$t.toml" "$AL/"; done
for t in xr-gp-cf0-send-uniformf xr-gp-cfN-send-uniformi xr-gp-customfilters-additional-uniform \
         xr-gp-multiinput-push-sampler xr-gp-cf0-fragment-shader-string; do
  cp "repo_atlas/eval/tasks-xrepo-gpuimage/$t.toml" "$AG/"; done
echo "libxcam=$(ls $AL | wc -l)  gpuimage=$(ls $AG | wc -l)"   # expect 10 and 5
```

- [ ] **Step 2: Run the adoption arms on libxcam** (one driver, sequential; no concurrency)

```bash
WT=/mnt/x/code/knowledgeLoop/.claude/worktrees/cm
REPO="$WT" PY="$WT/.venv/bin/python" EVAL_DIR=/home/vinc/repo-atlas-xrepo \
REPO_ATLAS_DB=/home/vinc/repo-atlas-xrepo/atlas-xrepo.db \
REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-xrepo/atlas-xrepo.toml \
MCP_CONFIG=/home/vinc/repo-atlas-xrepo/mcp-xrepo.json \
TASKS=/home/vinc/repo-atlas-xrepo/adopt-libxcam \
ARMS=control,optional,assisted SCORER=grounded-use LIMIT=0 TIMEOUT=300 INJECT_K=20 \
OUT=/home/vinc/repo-atlas-xrepo/adopt-libxcam.md \
bash scripts/run_eval_arms.sh > /home/vinc/repo-atlas-xrepo/adopt-libxcam.log 2>&1
```
Expected: a scorecard at `adopt-libxcam.md`. If the run printed `session limit reached … resume the
remaining N`, the scorecard covers only the clean tasks — **wait for the quota reset and re-run Step 2
with only the not-yet-done tasks** (remove completed `.toml`s from `$AL`, or re-run the whole dir next
window; partial scorecards from different windows are combined by hand in Step 5).

- [ ] **Step 3: Validate the batch is clean** (belt-and-suspenders; the harness now self-reports)

```bash
# 0 session-limit transcripts AND every run substantive (no 1-message deaths)
find ~/.claude/projects -maxdepth 2 -name '*.jsonl' -mmin -120 -path '*xr-ocl*' \
  | xargs grep -l "hit your session limit" 2>/dev/null | wc -l        # expect 0
```
If non-zero, discard that scorecard and resume next window.

- [ ] **Step 4: Run the adoption arms on gpuimage** (only if Step 2 finished clean and quota remains)

```bash
WT=/mnt/x/code/knowledgeLoop/.claude/worktrees/cm
REPO="$WT" PY="$WT/.venv/bin/python" EVAL_DIR=/home/vinc/repo-atlas-xrepo2 \
REPO_ATLAS_DB=/home/vinc/repo-atlas-xrepo2/atlas-xrepo2.db \
REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-xrepo2/atlas-xrepo2.toml \
MCP_CONFIG=/home/vinc/repo-atlas-xrepo2/mcp-xrepo2.json \
TASKS=/home/vinc/repo-atlas-xrepo2/adopt-gpuimage \
ARMS=control,optional,assisted SCORER=grounded-use LIMIT=0 TIMEOUT=300 INJECT_K=20 \
OUT=/home/vinc/repo-atlas-xrepo2/adopt-gpuimage.md \
bash scripts/run_eval_arms.sh > /home/vinc/repo-atlas-xrepo2/adopt-gpuimage.log 2>&1
```

- [ ] **Step 5: Read the contrasts, decide, record**

Pool the two scorecards (libxcam N=10 + gpuimage N=5) and the banked ceiling (`forced-inject 67%`
from `/home/vinc/repo-atlas-xrepo/ceiling-libxcam-lap8.md` + `…xrepo2/ceiling-gpuimage-lap8.md`).
Read from the per-arm table + `## Arm contrasts`:
- `captured (optional − control)` — expect ≈ 0 (the wall).
- **`assisted_lift (assisted − control)`** — the headline.
- `adoption_runs[assisted]` — did the gate fire AND the agent then call `find_related`.
- `turns` for `assisted` vs `control` — confirm no ballooning.

**Decision (this is the deliverable):**
- `assisted` ≈ ceiling (~67%) → the gated nudge works → next: productize the gate+nudge as a Claude
  Code hook/skill (new brainstorm).
- `assisted` ≈ control (~7%) → nudge insufficient → next: design the gated **auto-retrieve** hybrid
  (new brainstorm).
- in between → tune the gate (`k`, an all-top-K-absent variant) + the `NUDGE` wording; re-measure.

Record the numbers + the chosen branch as **Lap 9** in `docs/repo-atlas-evaluation.md` (timeline row +
section) and update the `repo-atlas-eval-null-result` memory. Commit; merge `worktree-cm → master`.

---

## Self-Review

**Spec coverage:**
- Part 1 — `_is_session_limit` (Task 1), `SessionLimitReached` (Task 1), `_run_agent` raises (Task 2),
  `run_multi_eval` stops clean + excludes partial task (Task 3). ✓
- Part 2 — measurement protocol: N=15 set, arms `control/optional/assisted` + banked ceiling, the
  contrasts, the decision tree, recording (Task 4). ✓
- Non-goals honored: no checkpoint/resume (Task 4 resume is manual), no `invalid` flag, no quota probe,
  no new adoption mechanism. ✓
- Testing section (judge-free, no `claude`): Tasks 1–3 each have unit tests. ✓

**Placeholder scan:** none — every code step shows complete code; every command is concrete.

**Type consistency:** `_is_session_limit(text)→bool`, `SessionLimitReached(Exception)`, and
`_run_agent(cmd, work)→dict` are used identically across Tasks 1–3; `run_multi_eval(tasks, runner,
arms, judge, exists_fn)` matches the existing signature; `RunResult(condition, diff="")` matches the
dataclass (condition positional, `diff` keyword). Consistent.
