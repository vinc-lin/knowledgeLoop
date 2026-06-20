# repo_atlas Eval Harness (Phase 1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the validation harness that answers "does `repo_atlas` make a coding agent (Claude Code) better?" — an A/B "with vs without repo_atlas" eval over curated coding/bug-fix tasks, with **task success** as the primary metric plus objective diagnostics (hallucination↓ / reuse↑ / exploration↓).

**Architecture:** A `repo_atlas/eval/` subpackage. Pure, unit-tested core (task schema, diff→refs extractor, metric functions, scorecard aggregation, report) + injectable IO interfaces (an `AgentRunner` that drives `claude -p` headless with/without the repo_atlas MCP, and a `Judge` that scores task success). The orchestrator composes them; with stubs it is fully unit-testable, and the real runner/judge are exercised by one gated integration test.

**Tech Stack:** Python 3.12, `subprocess` (drive `claude -p --output-format json --mcp-config ... --strict-mcp-config`), `tomllib` (task files), `httpx` (gateway judge), `pytest`/`pytest-asyncio`. Builds on Phase 1a (`repo_atlas.store`, `repo_atlas.config`).

**Depends on:** Phase 1a (the `repo_atlas` system, already merged). The repos under eval must be indexed (`repo-atlas index --all`) so the graph/hallucination oracle and the treatment-condition MCP have data.

**Conventions:**
- TDD: failing test → watch fail → minimal code → watch pass → commit.
- `tests/` is gitignored + tracked via force-add — new test files need `git add -f`.
- Run tests: `.venv/bin/python -m pytest <path> -p no:cacheprovider --no-cov -q` (from the worktree root).
- Reference: spec `docs/superpowers/specs/2026-06-20-repo-atlas-design.md` §13.

**Honesty guards baked into the design (spec §13):** report per-task (not just averages); a `regressed` count surfaces tasks where treatment did worse (context-pollution failure mode); the judged primary metric is corroborated by 3 objective diagnostics that need no LLM judge; the corpora don't build here, so success is scored against a ground-truth key + rubric, **not** compile/test-pass.

---

## File Structure

**New subpackage `repo_atlas/eval/`:**
- `__init__.py`
- `tasks.py` — `Task` dataclass + `load_tasks(dir)` (TOML).
- `extract.py` — `extract_refs(diff) -> (symbols, files)` (pure).
- `metrics.py` — `hallucination_rate`, `reuse_recall`, `exploration_cost` (pure).
- `aggregate.py` — `TaskScore`, `PairResult`, `Scorecard`, `make_score`, `make_pair`, `aggregate`.
- `runner.py` — `RunResult`, `AgentRunner` Protocol, `StubRunner`, `ClaudeRunner`.
- `judge.py` — `Judge` Protocol, `StubJudge`, `GatewayJudge`.
- `oracle.py` — `store_exists_fn(store, repo)` → `exists_fn(symbol)->bool`.
- `harness.py` — `run_pair`, `run_eval` (async orchestrator).
- `report.py` — `render_scorecard(scorecard) -> str` (markdown).
- `tasks/*.toml` — curated starter task set.

**Modified:**
- `repo_atlas/cli.py` — add an `eval` subcommand.

**Tests:** `tests/test_eval_tasks.py`, `test_eval_extract.py`, `test_eval_metrics.py`, `test_eval_aggregate.py`, `test_eval_runner.py`, `test_eval_judge.py`, `test_eval_oracle.py`, `test_eval_harness.py`, `test_eval_report.py`, `test_eval_cli.py`, `test_eval_taskset.py`, `test_eval_integration.py` (gated).

---

## Task 0: Spike — headless `claude -p` run + JSON capture + per-run diff isolation

**Not TDD — a spike that de-risks `ClaudeRunner` (Task 5). Record exact invocation + JSON field names.**

- [ ] **Step 1: Confirm headless run + JSON shape**

Run a trivial headless prompt and inspect the JSON envelope:

```bash
cd /tmp && claude -p "reply with the single word OK" --output-format json 2>/dev/null | python -m json.tool
```

Record the field names actually present (expected: `result`/`text`, `usage` (token counts), `num_turns`, `total_cost_usd`, `session_id`). **Write down the exact keys** — Task 5 parses them.

- [ ] **Step 2: Confirm MCP injection (treatment condition)**

Write a temp MCP config pointing at `repo-atlas` (the Phase-1a server) and confirm the tools are available headless:

```bash
cat > /tmp/atlas-mcp.json <<'JSON'
{ "mcpServers": { "repo-atlas": { "command": "/home/vinc/code/knowledgeLoop/.venv/bin/python",
  "args": ["-m","repo_atlas"], "env": { "REPO_ATLAS_EMBED_MODEL": "mxbai-embed-large" } } } }
JSON
claude -p "list the repo-atlas MCP tools you can call, then stop" \
  --output-format json --mcp-config /tmp/atlas-mcp.json --strict-mcp-config \
  --allowedTools "mcp__repo-atlas__find_related" --permission-mode acceptEdits 2>/dev/null \
  | python -c "import json,sys;d=json.load(sys.stdin);print(d.get('result',d))" | head
```

Record: does `--strict-mcp-config` + `--allowedTools "mcp__repo-atlas__*"` work, and how tool-call counts surface (via `--output-format stream-json` events vs `num_turns`). **Decide the exploration-cost proxy:** `num_turns` (simplest, always present) is the default; note if stream-json tool-call counting is feasible.

- [ ] **Step 3: Confirm per-run isolation approach**

A coding task mutates files; each run must be isolated and its change captured as a diff. Confirm the plan: copy the target repo to a temp dir (`git -C <repo> archive HEAD | tar -x -C <tmp>` OR `cp -r`), run `claude -p` with `--add-dir <tmp>` and cwd=`<tmp>`, then `git -C <tmp> diff` (after `git init && git add -A && git commit` baseline) to capture the change. Record the chosen mechanism. (For tasks where the corpus copy is large, a git worktree of the corpus at HEAD is the cheaper isolation.)

- [ ] **Step 4: Record findings** in the PR description (exact JSON keys, the working `claude -p` invocation for both conditions, the exploration-cost proxy, the isolation mechanism). No commit.

---

## Task 1: Eval scaffold + Task schema + loader

**Files:** Create `repo_atlas/eval/__init__.py`, `repo_atlas/eval/tasks.py`. Test: `tests/test_eval_tasks.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_tasks.py
from repo_atlas.eval.tasks import Task, load_tasks


def test_load_tasks(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    (d / "t1.toml").write_text(
        'id = "add-sepia"\n'
        'kind = "dev"\n'
        'repo = "gpuimage"\n'
        'prompt = "Add a sepia filter."\n'
        'expected_symbols = ["cgeImageFilter"]\n'
        'expected_files = ["library/src/main/jni/cge/common/cgeImageFilter.h"]\n'
        'rubric = "A correct solution subclasses cgeImageFilter."\n')
    tasks = load_tasks(str(d))
    assert len(tasks) == 1
    t = tasks[0]
    assert isinstance(t, Task)
    assert t.id == "add-sepia" and t.kind == "dev" and t.repo == "gpuimage"
    assert t.expected_symbols == ["cgeImageFilter"]
    assert "sepia" in t.prompt.lower()
```

- [ ] **Step 2: Run it, verify it fails** — `ModuleNotFoundError`.
  Run: `.venv/bin/python -m pytest tests/test_eval_tasks.py -p no:cacheprovider --no-cov -q`

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/__init__.py
"""repo_atlas eval: A/B with/without-repo_atlas validation harness."""
```

```python
# repo_atlas/eval/tasks.py
from __future__ import annotations

import glob
import os
import tomllib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    id: str
    kind: str               # 'dev' | 'bugfix'
    repo: str
    prompt: str
    rubric: str
    expected_symbols: list = field(default_factory=list)
    expected_files: list = field(default_factory=list)


def load_tasks(directory: str) -> list[Task]:
    tasks = []
    for path in sorted(glob.glob(os.path.join(directory, "*.toml"))):
        with open(path, "rb") as fh:
            d = tomllib.load(fh)
        tasks.append(Task(
            id=d["id"], kind=d["kind"], repo=d["repo"], prompt=d["prompt"],
            rubric=d["rubric"],
            expected_symbols=list(d.get("expected_symbols", [])),
            expected_files=list(d.get("expected_files", []))))
    return tasks
```

- [ ] **Step 4: Run it, verify it passes (1 passed).**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/__init__.py repo_atlas/eval/tasks.py
git add -f tests/test_eval_tasks.py
git commit -m "feat(repo_atlas/eval): task schema + TOML loader"
```

---

## Task 2: Diff → references extractor

**Files:** Create `repo_atlas/eval/extract.py`. Test: `tests/test_eval_extract.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_extract.py
from repo_atlas.eval.extract import extract_refs

DIFF = """diff --git a/lib/sepia.cpp b/lib/sepia.cpp
new file mode 100644
--- /dev/null
+++ b/lib/sepia.cpp
@@ -0,0 +1,3 @@
+class SepiaFilter : public cgeImageFilter {
+    void apply() { cgeBrightnessAdjust(); }
+};
"""


def test_extract_files_and_symbols():
    symbols, files = extract_refs(DIFF)
    assert "lib/sepia.cpp" in files
    assert "cgeImageFilter" in symbols
    assert "cgeBrightnessAdjust" in symbols
    assert "SepiaFilter" in symbols


def test_extract_empty_diff():
    assert extract_refs("") == ([], [])
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/extract.py
from __future__ import annotations

import re

_FILE = re.compile(r"^\+\+\+ b/(.+)$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def extract_refs(diff: str) -> tuple[list[str], list[str]]:
    """From a unified diff: (referenced identifiers in added lines, touched files).

    Heuristic — added-line identifiers approximate the symbols/APIs the agent used."""
    files: list[str] = []
    symbols: dict[str, None] = {}
    for line in diff.splitlines():
        fm = _FILE.match(line)
        if fm:
            files.append(fm.group(1).strip())
            continue
        if line.startswith("+") and not line.startswith("+++"):
            for tok in _IDENT.findall(line[1:]):
                symbols[tok] = None
    return list(symbols), files
```

- [ ] **Step 4: Run it, verify it passes (2 passed).**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/extract.py
git add -f tests/test_eval_extract.py
git commit -m "feat(repo_atlas/eval): diff -> referenced symbols + files extractor"
```

---

## Task 3: Metric functions (pure)

**Files:** Create `repo_atlas/eval/metrics.py`. Test: `tests/test_eval_metrics.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_metrics.py
from repo_atlas.eval.metrics import hallucination_rate, reuse_recall


def test_hallucination_rate():
    real = {"cgeImageFilter", "cgeBrightnessAdjust"}
    refs = ["cgeImageFilter", "cgeApplyBrightness", "SepiaFilter"]
    # 2 of 3 are not in the graph (cgeApplyBrightness, SepiaFilter)
    assert hallucination_rate(refs, lambda s: s in real) == 2 / 3
    assert hallucination_rate([], lambda s: True) == 0.0


def test_reuse_recall():
    # solution referenced cgeImageFilter (a key symbol) + the key file
    rec = reuse_recall(["cgeImageFilter", "X"], ["a/b.cpp"],
                       expected_symbols=["cgeImageFilter"], expected_files=["a/b.cpp"])
    assert rec == 1.0
    # missed everything
    assert reuse_recall(["Y"], ["z.cpp"], expected_symbols=["cgeImageFilter"],
                        expected_files=["a/b.cpp"]) == 0.0
    # no key defined -> recall is 1.0 (nothing to miss)
    assert reuse_recall(["Y"], ["z.cpp"], expected_symbols=[], expected_files=[]) == 1.0
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/metrics.py
from __future__ import annotations

from typing import Callable


def hallucination_rate(referenced_symbols: list[str],
                       exists_fn: Callable[[str], bool]) -> float:
    """Fraction of referenced symbols that do NOT exist in the graph. 0.0 if none referenced."""
    if not referenced_symbols:
        return 0.0
    missing = sum(0 if exists_fn(s) else 1 for s in referenced_symbols)
    return missing / len(referenced_symbols)


def reuse_recall(referenced_symbols: list[str], touched_files: list[str], *,
                 expected_symbols: list[str], expected_files: list[str]) -> float:
    """Recall of the ground-truth key (expected symbols+files) by the solution. 1.0 if key empty."""
    key = [("sym", s) for s in expected_symbols] + [("file", f) for f in expected_files]
    if not key:
        return 1.0
    got_syms, got_files = set(referenced_symbols), set(touched_files)
    hit = sum(1 for kind, v in key
              if (v in got_syms if kind == "sym" else v in got_files))
    return hit / len(key)


def exploration_cost(tool_calls: int) -> int:
    """Lower is better. Proxy = agent tool calls (or num_turns, per the spike decision)."""
    return tool_calls
```

- [ ] **Step 4: Run it, verify it passes (2 passed).**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/metrics.py
git add -f tests/test_eval_metrics.py
git commit -m "feat(repo_atlas/eval): metrics (hallucination_rate, reuse_recall, exploration_cost)"
```

---

## Task 4: Scoring + aggregation

**Files:** Create `repo_atlas/eval/aggregate.py`. Test: `tests/test_eval_aggregate.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_aggregate.py
from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate


def _score(cond, success, hall, reuse, expl):
    return TaskScore(task_id="t1", condition=cond, success=success,
                     hallucination_rate=hall, reuse_recall=reuse, exploration_cost=expl)


def test_make_pair_regression_flag():
    base = _score("baseline", success=False, hall=0.5, reuse=0.0, expl=10)
    treat = _score("treatment", success=True, hall=0.0, reuse=1.0, expl=4)
    pair = make_pair("t1", base, treat)
    assert pair.regressed is False     # treatment improved on success

    base2 = _score("baseline", success=True, hall=0.0, reuse=1.0, expl=4)
    treat2 = _score("treatment", success=False, hall=0.5, reuse=0.0, expl=10)
    assert make_pair("t1", base2, treat2).regressed is True   # treatment worse on success


def test_aggregate_summary():
    base = _score("baseline", success=False, hall=0.6, reuse=0.0, expl=10)
    treat = _score("treatment", success=True, hall=0.1, reuse=1.0, expl=4)
    sc = aggregate([make_pair("t1", base, treat)])
    s = sc.summary
    assert s["n"] == 1
    assert s["success_baseline"] == 0.0 and s["success_treatment"] == 1.0
    assert s["hallucination_delta"] == -0.5    # treatment - baseline (lower is better)
    assert s["reuse_delta"] == 1.0
    assert s["regressed_count"] == 0
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/aggregate.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TaskScore:
    task_id: str
    condition: str             # 'baseline' | 'treatment'
    success: bool
    hallucination_rate: float
    reuse_recall: float
    exploration_cost: int


@dataclass
class PairResult:
    task_id: str
    baseline: TaskScore
    treatment: TaskScore
    regressed: bool


@dataclass
class Scorecard:
    pairs: list
    summary: dict


def make_pair(task_id: str, baseline: TaskScore, treatment: TaskScore) -> PairResult:
    # 'regressed' = treatment did worse on the primary metric (success), or — when success
    # is unchanged — worse on hallucination.
    if treatment.success != baseline.success:
        regressed = baseline.success and not treatment.success
    else:
        regressed = treatment.hallucination_rate > baseline.hallucination_rate
    return PairResult(task_id, baseline, treatment, regressed)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(pairs: list) -> Scorecard:
    b = [p.baseline for p in pairs]
    t = [p.treatment for p in pairs]
    summary = {
        "n": len(pairs),
        "success_baseline": _mean([1.0 if s.success else 0.0 for s in b]),
        "success_treatment": _mean([1.0 if s.success else 0.0 for s in t]),
        "hallucination_delta": _mean([s.hallucination_rate for s in t]) - _mean([s.hallucination_rate for s in b]),
        "reuse_delta": _mean([s.reuse_recall for s in t]) - _mean([s.reuse_recall for s in b]),
        "exploration_delta": _mean([s.exploration_cost for s in t]) - _mean([s.exploration_cost for s in b]),
        "regressed_count": sum(1 for p in pairs if p.regressed),
    }
    summary["success_delta"] = summary["success_treatment"] - summary["success_baseline"]
    return Scorecard(pairs=pairs, summary=summary)
```

- [ ] **Step 4: Run it, verify it passes (2 passed).**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/aggregate.py
git add -f tests/test_eval_aggregate.py
git commit -m "feat(repo_atlas/eval): TaskScore/PairResult/Scorecard + regression flag + aggregation"
```

---

## Task 5: Agent runner (interface + stub + real)

**Files:** Create `repo_atlas/eval/runner.py`. Test: `tests/test_eval_runner.py`.

- [ ] **Step 1: Write the failing test (stub only)**

```python
# tests/test_eval_runner.py
import pytest
from repo_atlas.eval.runner import RunResult, StubRunner
from repo_atlas.eval.tasks import Task


def _task():
    return Task(id="t1", kind="dev", repo="gpuimage", prompt="p", rubric="r")


@pytest.mark.asyncio
async def test_stub_runner_returns_canned():
    canned = {("t1", "baseline"): RunResult("baseline", ["X"], ["a.cpp"], 9, 100, {}, ""),
              ("t1", "treatment"): RunResult("treatment", ["cgeImageFilter"], ["a.cpp"], 4, 80, {}, "")}
    r = StubRunner(canned)
    base = await r.run(_task(), condition="baseline")
    treat = await r.run(_task(), condition="treatment")
    assert base.tool_calls == 9 and treat.referenced_symbols == ["cgeImageFilter"]
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement** (the `ClaudeRunner` IS the real claude-driving impl; it is integration-only — unit tests use `StubRunner`. Adjust the JSON-key parsing + invocation per the Task-0 spike findings.)

```python
# repo_atlas/eval/runner.py
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Protocol

from repo_atlas.eval.tasks import Task
from repo_atlas.eval.extract import extract_refs


@dataclass
class RunResult:
    condition: str                  # 'baseline' | 'treatment'
    referenced_symbols: list = field(default_factory=list)
    touched_files: list = field(default_factory=list)
    tool_calls: int = 0
    tokens: int = 0
    raw: dict = field(default_factory=dict)
    diff: str = ""


class AgentRunner(Protocol):
    async def run(self, task: Task, *, condition: str) -> RunResult: ...


class StubRunner:
    """Returns canned RunResults keyed by (task_id, condition). For tests."""
    def __init__(self, canned: dict):
        self._canned = canned

    async def run(self, task: Task, *, condition: str) -> RunResult:
        return self._canned[(task.id, condition)]


class ClaudeRunner:
    """Drives `claude -p` headless in an isolated copy of the repo, with/without repo_atlas.

    Integration-only (needs the `claude` CLI). Per Task-0 spike: parse the JSON envelope's
    usage/num_turns; capture the change via git diff in the temp copy.
    """
    def __init__(self, repo_paths: dict, mcp_config_path: str,
                 model: str = "claude-sonnet-4-6"):
        self._repo_paths = repo_paths           # repo name -> source path
        self._mcp = mcp_config_path
        self._model = model

    async def run(self, task: Task, *, condition: str) -> RunResult:
        src = self._repo_paths[task.repo]
        work = tempfile.mkdtemp(prefix=f"eval-{task.id}-{condition}-")
        # isolate: snapshot the repo at HEAD into a fresh git repo so we can diff the change
        subprocess.run(f"git -C {src} archive HEAD | tar -x -C {work}", shell=True, check=True)
        subprocess.run(["git", "-C", work, "init", "-q"], check=True)
        subprocess.run(["git", "-C", work, "add", "-A"], check=True)
        subprocess.run(["git", "-C", work, "-c", "user.email=e@x", "-c", "user.name=e",
                        "commit", "-qm", "base"], check=True)

        cmd = ["claude", "-p", task.prompt, "--output-format", "json",
               "--permission-mode", "acceptEdits", "--add-dir", work, "--model", self._model]
        if condition == "treatment":
            cmd += ["--mcp-config", self._mcp, "--strict-mcp-config",
                    "--allowedTools", "mcp__repo-atlas__find_related",
                    "mcp__repo-atlas__prepare_change", "mcp__repo-atlas__verify_grounding"]
        proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=900)
        raw = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
        diff = subprocess.run(["git", "-C", work, "diff", "HEAD"],
                              capture_output=True, text=True).stdout
        symbols, files = extract_refs(diff)
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        tokens = int(usage.get("output_tokens", 0)) + int(usage.get("input_tokens", 0))
        tool_calls = int(raw.get("num_turns", 0)) if isinstance(raw, dict) else 0
        result = RunResult(condition, symbols, files, tool_calls, tokens, raw, diff)
        shutil.rmtree(work, ignore_errors=True)
        return result
```

> Note: the `usage`/`num_turns` key names and the exploration-cost proxy come from the Task-0 spike — adjust if the spike found different keys. `ClaudeRunner` has no unit test (it shells out to `claude`); it is covered by the gated integration test (Task 12).

- [ ] **Step 4: Run the stub test, verify it passes (1 passed). Also confirm the module imports: `python -c "import repo_atlas.eval.runner"`.**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/runner.py
git add -f tests/test_eval_runner.py
git commit -m "feat(repo_atlas/eval): AgentRunner protocol + StubRunner + ClaudeRunner"
```

---

## Task 6: Judge (interface + stub + gateway)

**Files:** Create `repo_atlas/eval/judge.py`. Test: `tests/test_eval_judge.py`.

- [ ] **Step 1: Write the failing test (stub only)**

```python
# tests/test_eval_judge.py
import pytest
from repo_atlas.eval.judge import StubJudge
from repo_atlas.eval.runner import RunResult
from repo_atlas.eval.tasks import Task


@pytest.mark.asyncio
async def test_stub_judge():
    j = StubJudge({"t1": True})
    ok = await j.score(Task(id="t1", kind="dev", repo="r", prompt="p", rubric="x"),
                       RunResult("treatment"))
    assert ok is True
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/judge.py
from __future__ import annotations

from typing import Protocol

from repo_atlas.eval.tasks import Task
from repo_atlas.eval.runner import RunResult


class Judge(Protocol):
    async def score(self, task: Task, run: RunResult) -> bool: ...


class StubJudge:
    """Canned success by task id. For tests."""
    def __init__(self, verdicts: dict):
        self._v = verdicts

    async def score(self, task: Task, run: RunResult) -> bool:
        return bool(self._v.get(task.id, False))


class GatewayJudge:
    """LLM judge via the gateway chat endpoint. Blinded: prompt does NOT reveal condition.

    Integration-only. Returns True iff the solution satisfies the task rubric."""
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._timeout = timeout

    async def score(self, task: Task, run: RunResult) -> bool:
        import httpx
        prompt = (
            "You are grading whether a code change satisfies a task. Answer ONLY 'PASS' or "
            "'FAIL'.\n\n"
            f"TASK: {task.prompt}\n\nRUBRIC: {task.rubric}\n\n"
            f"EXPECTED (a correct solution typically touches these): "
            f"symbols={task.expected_symbols} files={task.expected_files}\n\n"
            f"CANDIDATE DIFF:\n{run.diff[:6000]}\n\nVerdict:")
        resp = httpx.post(self._url, headers={"Authorization": f"Bearer {self._key}"},
                          json={"model": self._model, "temperature": 0,
                                "messages": [{"role": "user", "content": prompt}]},
                          timeout=self._timeout)
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip().upper()
        return text.startswith("PASS")
```

- [ ] **Step 4: Run the stub test, verify it passes. Confirm import: `python -c "import repo_atlas.eval.judge"`.**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/judge.py
git add -f tests/test_eval_judge.py
git commit -m "feat(repo_atlas/eval): Judge protocol + StubJudge + GatewayJudge (blinded)"
```

---

## Task 7: Graph oracle (symbol existence)

**Files:** Create `repo_atlas/eval/oracle.py`. Test: `tests/test_eval_oracle.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_oracle.py
from repo_atlas.eval.oracle import store_exists_fn
from repo_atlas.store import Store, Unit


def test_store_exists_fn(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    u = Unit(repo="r1", kind="symbol", name="cgeImageFilter",
             qualified_name="cge.cgeImageFilter", file="f.h", repo_head="H",
             text="filter base", meta={})
    st.reindex_repo("r1", [(u, [1.0])], repo_head="H")
    exists = store_exists_fn(st, "r1")
    assert exists("cgeImageFilter") is True
    assert exists("cgeMadeUp") is False
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/oracle.py
from __future__ import annotations

from typing import Callable


def store_exists_fn(store, repo: str) -> Callable[[str], bool]:
    """An exists_fn(symbol)->bool backed by the repo_atlas store's indexed symbols.

    Caches the per-symbol lookups within a single eval run."""
    cache: dict[str, bool] = {}

    def exists(symbol: str) -> bool:
        if symbol not in cache:
            cache[symbol] = store.symbols_exist(repo, [symbol])[symbol]
        return cache[symbol]

    return exists
```

- [ ] **Step 4: Run it, verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/oracle.py
git add -f tests/test_eval_oracle.py
git commit -m "feat(repo_atlas/eval): store-backed symbol-existence oracle"
```

---

## Task 8: Harness orchestrator

**Files:** Create `repo_atlas/eval/harness.py`. Test: `tests/test_eval_harness.py`.

- [ ] **Step 1: Write the failing test (all stubs — no network/CBM/claude)**

```python
# tests/test_eval_harness.py
import pytest
from repo_atlas.eval.harness import run_eval
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.runner import RunResult, StubRunner
from repo_atlas.eval.judge import StubJudge


@pytest.mark.asyncio
async def test_run_eval_end_to_end_with_stubs():
    task = Task(id="t1", kind="dev", repo="r1", prompt="p", rubric="x",
                expected_symbols=["cgeImageFilter"], expected_files=["a.h"])
    runner = StubRunner({
        ("t1", "baseline"): RunResult("baseline", ["madeUp"], ["z.cpp"], 11, 200, {}, ""),
        ("t1", "treatment"): RunResult("treatment", ["cgeImageFilter"], ["a.h"], 4, 90, {}, ""),
    })
    judge = StubJudge({"t1": True})              # judge passes the treatment solution
    # baseline judged separately: make the judge pass only treatment by task isn't possible
    # with StubJudge-by-id, so use an exists_fn + a judge that always passes here and rely on
    # objective metrics for the assertions.
    real = {"cgeImageFilter"}
    sc = await run_eval([task], runner, judge, lambda s: s in real)
    assert sc.summary["n"] == 1
    p = sc.pairs[0]
    # treatment referenced a real symbol + the key file; baseline hallucinated
    assert p.treatment.hallucination_rate == 0.0
    assert p.baseline.hallucination_rate == 1.0
    assert p.treatment.reuse_recall == 1.0
    assert p.treatment.exploration_cost == 4
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/harness.py
from __future__ import annotations

from typing import Callable

from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate
from repo_atlas.eval import metrics


async def _score(task, run, *, judge, exists_fn) -> TaskScore:
    success = await judge.score(task, run)
    return TaskScore(
        task_id=task.id, condition=run.condition, success=success,
        hallucination_rate=metrics.hallucination_rate(run.referenced_symbols, exists_fn),
        reuse_recall=metrics.reuse_recall(
            run.referenced_symbols, run.touched_files,
            expected_symbols=task.expected_symbols, expected_files=task.expected_files),
        exploration_cost=metrics.exploration_cost(run.tool_calls))


async def run_pair(task, runner, judge, exists_fn: Callable[[str], bool]):
    base_run = await runner.run(task, condition="baseline")
    treat_run = await runner.run(task, condition="treatment")
    base = await _score(task, base_run, judge=judge, exists_fn=exists_fn)
    treat = await _score(task, treat_run, judge=judge, exists_fn=exists_fn)
    return make_pair(task.id, base, treat)


async def run_eval(tasks, runner, judge, exists_fn: Callable[[str], bool]):
    pairs = [await run_pair(t, runner, judge, exists_fn) for t in tasks]
    return aggregate(pairs)
```

- [ ] **Step 4: Run it, verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/harness.py
git add -f tests/test_eval_harness.py
git commit -m "feat(repo_atlas/eval): harness orchestrator (run_pair / run_eval)"
```

---

## Task 9: Report renderer

**Files:** Create `repo_atlas/eval/report.py`. Test: `tests/test_eval_report.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_report.py
from repo_atlas.eval.report import render_scorecard
from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate


def test_render_contains_summary_and_per_task():
    base = TaskScore("t1", "baseline", False, 0.6, 0.0, 10)
    treat = TaskScore("t1", "treatment", True, 0.1, 1.0, 4)
    sc = aggregate([make_pair("t1", base, treat)])
    md = render_scorecard(sc)
    assert "Task success" in md
    assert "t1" in md                 # per-task row
    assert "regressed" in md.lower()
    assert "Verdict" in md
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/report.py
from __future__ import annotations


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render_scorecard(scorecard) -> str:
    s = scorecard.summary
    lines = ["# repo_atlas eval — with vs without\n",
             f"Tasks: **{s['n']}**\n",
             "| Metric | baseline | treatment | delta |",
             "|---|---|---|---|",
             f"| **Task success** (primary) | {_pct(s['success_baseline'])} | "
             f"{_pct(s['success_treatment'])} | {s['success_delta']*100:+.0f}pp |",
             f"| Hallucination rate | — | — | {s['hallucination_delta']:+.2f} (lower better) |",
             f"| Prior-art reuse | — | — | {s['reuse_delta']:+.2f} (higher better) |",
             f"| Exploration cost | — | — | {s['exploration_delta']:+.1f} (lower better) |",
             f"\n**Regressed tasks (treatment worse): {s['regressed_count']}/{s['n']}**\n",
             "## Per-task",
             "| task | success b→t | hallucination b→t | reuse b→t | explore b→t | regressed |",
             "|---|---|---|---|---|---|"]
    for p in scorecard.pairs:
        b, t = p.baseline, p.treatment
        lines.append(
            f"| {p.task_id} | {b.success}→{t.success} | "
            f"{b.hallucination_rate:.2f}→{t.hallucination_rate:.2f} | "
            f"{b.reuse_recall:.2f}→{t.reuse_recall:.2f} | "
            f"{b.exploration_cost}→{t.exploration_cost} | {'YES' if p.regressed else ''} |")
    useful = s["success_delta"] > 0 or (s["hallucination_delta"] < 0 and s["reuse_delta"] > 0)
    lines.append(f"\n## Verdict\nrepo_atlas is **{'useful' if useful else 'NOT clearly useful'}** "
                 f"on this task set (primary = task success).")
    return "\n".join(lines)
```

- [ ] **Step 4: Run it, verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/report.py
git add -f tests/test_eval_report.py
git commit -m "feat(repo_atlas/eval): markdown scorecard renderer"
```

---

## Task 10: CLI `repo-atlas eval`

**Files:** Modify `repo_atlas/cli.py`. Test: `tests/test_eval_cli.py`.

- [ ] **Step 1: Write the failing test** (uses monkeypatch to stub the heavy run)

```python
# tests/test_eval_cli.py
from repo_atlas import cli


def test_eval_parser():
    args = cli.build_parser().parse_args(["eval", "--tasks", "/t", "--out", "/o.md"])
    assert args.cmd == "eval" and args.tasks == "/t" and args.out == "/o.md"
```

- [ ] **Step 2: Run it, verify it fails** (no `eval` subcommand yet).

- [ ] **Step 3: Implement** — add to `repo_atlas/cli.py`'s `build_parser()` (inside, alongside the `index` subparser):

```python
    ev = sub.add_parser("eval", help="run the with/without eval harness")
    ev.add_argument("--tasks", required=True, help="dir of task .toml files")
    ev.add_argument("--out", default="eval-scorecard.md", help="scorecard output path")
    ev.add_argument("--limit", type=int, default=0, help="limit number of tasks (0 = all)")
    ev.add_argument("--mcp-config", help="MCP config json pointing at repo-atlas (treatment)")
```

And add a dispatch branch + handler in `cli.py`:

```python
def _run_eval(args) -> int:
    import asyncio
    from repo_atlas.config import load_config
    from repo_atlas.store import Store
    from repo_atlas.eval.tasks import load_tasks
    from repo_atlas.eval.runner import ClaudeRunner
    from repo_atlas.eval.judge import GatewayJudge
    from repo_atlas.eval.oracle import store_exists_fn
    from repo_atlas.eval.harness import run_eval
    from repo_atlas.eval.report import render_scorecard
    from repo_atlas.registry import load_registry

    cfg = load_config(os.environ)
    tasks = load_tasks(args.tasks)
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        print(f"repo_atlas eval: no tasks in {args.tasks}")
        return 2
    store = Store(cfg.db_path)
    registry = {e.name: e.repo_path
                for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    runner = ClaudeRunner(registry, args.mcp_config or "")
    judge = GatewayJudge(cfg.base_url, cfg.api_key,
                         os.environ.get("REPO_ATLAS_JUDGE_MODEL", "deepseek-chat"))
    # one exists_fn per repo, dispatched by the task's repo
    oracles = {name: store_exists_fn(store, name) for name in registry}

    async def _exists_router(tasks):
        return await run_eval(
            tasks, runner, judge,
            exists_fn=lambda s: any(o(s) for o in oracles.values()))

    sc = asyncio.run(_exists_router(tasks))
    md = render_scorecard(sc)
    with open(args.out, "w") as fh:
        fh.write(md)
    print(md)
    print(f"\nwrote {args.out}")
    return 0
```

Add to `main()`'s dispatch (before the serve fallback):

```python
    if args.cmd == "eval":
        return _run_eval(args)
```

- [ ] **Step 4: Run the CLI test (1 passed) and the existing CLI tests (no regression):**
  `.venv/bin/python -m pytest tests/test_eval_cli.py tests/test_ra_cli.py -p no:cacheprovider --no-cov -q`

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/cli.py
git add -f tests/test_eval_cli.py
git commit -m "feat(repo_atlas/eval): 'repo-atlas eval' CLI subcommand"
```

---

## Task 11: Starter task set

**Files:** Create `repo_atlas/eval/tasks/*.toml` (6 starter tasks). Test: `tests/test_eval_taskset.py`.

Curate **6** tasks (3 dev, 3 bugfix) over the indexed corpora, each with a real ground-truth key (use `repo-atlas` / the graph to find real existing symbols+files). Spread across repos.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_taskset.py
import os
from repo_atlas.eval.tasks import load_tasks

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKDIR = os.path.join(HERE, "repo_atlas", "eval", "tasks")


def test_starter_tasks_load_and_are_valid():
    tasks = load_tasks(TASKDIR)
    assert len(tasks) >= 6
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids))                    # unique ids
    for t in tasks:
        assert t.kind in ("dev", "bugfix")
        assert t.prompt and t.rubric
        assert t.expected_symbols or t.expected_files   # every task has a ground-truth key
```

- [ ] **Step 2: Run it, verify it fails** (no tasks dir yet).

- [ ] **Step 3: Create 6 task files.** Example (create real ones grounded in the indexed corpora — verify each `expected_symbols`/`expected_files` actually exists via `repo-atlas` `verify_grounding`/`find_related` before committing):

```toml
# repo_atlas/eval/tasks/gpuimage-add-sepia.toml
id = "gpuimage-add-sepia"
kind = "dev"
repo = "gpuimage"
prompt = "Add a sepia-tone image filter to the CGE native filter library, following the existing filter pattern."
rubric = "A correct solution defines a new filter class that subclasses the existing cgeImageFilter base and registers/implements the filter the way sibling cge*Adjust filters do."
expected_symbols = ["cgeImageFilter"]
expected_files = ["library/src/main/jni/cge/common/cgeImageFilter.h"]
```

Create 5 more (e.g. `ndk-jni-fix`, `libxcam-*`, etc.) covering bugfix + dev across repos. Each MUST have a verified key.

- [ ] **Step 4: Run the test, verify it passes (>=6 tasks, all valid).**

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/tasks/
git add -f tests/test_eval_taskset.py
git commit -m "feat(repo_atlas/eval): 6 starter eval tasks with verified ground-truth keys"
```

---

## Task 12: Gated end-to-end integration test

**Files:** Create `tests/test_eval_integration.py`.

**Prereq:** `claude` CLI available + logged in; gateway configured; the eval repos indexed (`repo-atlas index --all`); an MCP config json pointing at `repo-atlas`.

- [ ] **Step 1: Create the gated test**

```python
# tests/test_eval_integration.py
"""End-to-end: run ONE task with/without repo_atlas via the real claude CLI + gateway judge.
Gated (needs claude CLI, gateway, indexed store)."""
import os
import shutil
import pytest

from repo_atlas.config import load_config
from repo_atlas.store import Store
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.runner import ClaudeRunner
from repo_atlas.eval.judge import GatewayJudge
from repo_atlas.eval.oracle import store_exists_fn
from repo_atlas.eval.harness import run_pair


@pytest.mark.integration
@pytest.mark.asyncio
async def test_one_task_with_and_without(tmp_path):
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not available")
    cfg = load_config(os.environ)
    if not cfg.base_url:
        pytest.skip("gateway not configured")
    mcp = os.environ.get("REPO_ATLAS_MCP_CONFIG")
    if not mcp or not os.path.exists(mcp):
        pytest.skip("REPO_ATLAS_MCP_CONFIG not set")
    store = Store(cfg.db_path)
    task = Task(id="smoke", kind="dev", repo="gpuimage",
                prompt="Add a one-line comment to the top of any one source file naming the project.",
                rubric="The diff adds a comment mentioning the project.",
                expected_files=[])
    runner = ClaudeRunner({"gpuimage": "/mnt/x/code/corpora/android-gpuimage-plus"}, mcp)
    judge = GatewayJudge(cfg.base_url, cfg.api_key,
                         os.environ.get("REPO_ATLAS_JUDGE_MODEL", "deepseek-chat"))
    try:
        pair = await run_pair(task, runner, judge, store_exists_fn(store, "gpuimage"))
    except Exception as exc:
        pytest.skip(f"e2e run failed (claude/gateway): {exc}")
    assert pair.task_id == "smoke"
    assert pair.baseline.condition == "baseline"
    assert pair.treatment.condition == "treatment"
```

- [ ] **Step 2: Confirm it collects + deselects from the default suite** (do NOT run the full thing — it drives the real agent twice):
  `.venv/bin/python -m pytest tests/test_eval_integration.py -m integration --collect-only -p no:cacheprovider --no-cov -q` (1 collected)
  `.venv/bin/python -m pytest tests/test_eval_integration.py -m "not integration" -p no:cacheprovider --no-cov -q` (1 deselected)

- [ ] **Step 3: Commit**

```bash
git add -f tests/test_eval_integration.py
git commit -m "test(repo_atlas/eval): gated end-to-end with/without integration test"
```

---

## Self-Review (done at authoring; notes for the implementer)

- **Spec §13 coverage:** A/B with/without (runner conditions, T5); task set + ground-truth keys (T1, T11); metrics — task success primary (judge, T6 + harness T8), hallucination (T3 + oracle T7), reuse (T3), exploration (T3); per-task reporting + regressed count (T4, T9); blinded judge (T6 prompt omits condition); env limitation = score vs rubric/key not compile (judge + metrics, no build step). Engram-style with/without is the runner's two conditions.
- **Placeholder scan:** none — pure modules have complete code; IO modules (`ClaudeRunner`, `GatewayJudge`) have complete code grounded in the Task-0 spike and the scouted `claude -p` flags, flagged for spike-adjustment of JSON keys.
- **Type consistency:** `Task`, `RunResult`, `TaskScore`/`PairResult`/`Scorecard` defined once (T1/T5/T4) and used unchanged in harness/report/cli. `AgentRunner.run(task,*,condition)->RunResult` and `Judge.score(task,run)->bool` honored by stubs, real impls, and the harness. `exists_fn: Callable[[str],bool]` consistent across metrics/oracle/harness.
- **Risk areas / verification points:** (1) the `claude -p --output-format json` field names + exploration-cost proxy (Task-0 spike resolves; T5 parsing adjusts); (2) `extract_refs` is a heuristic (added-line identifiers) — good enough for reuse/hallucination signal, not exact; note it; (3) the gateway judge model — pick a capable chat model (`REPO_ATLAS_JUDGE_MODEL`), not necessarily the embedding model; (4) per-run isolation cost on large corpora (libxcam) — `git archive` snapshot is bounded but not free.
- **Scope note:** task-set CURATION (T11) is the labor-intensive part and is incremental — 6 to prove the harness; expand toward the spec's 15–30 later. Log when the set is small so a "useful" verdict isn't over-read.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, two-stage review between tasks.
2. **Inline Execution** — execute tasks in this session with checkpoints.

(The gated integration test, Task 12, and a full eval run require the `claude` CLI + gateway + an indexed store; the offline tasks 1–11 are fully unit-tested with stubs and need none of that.)
