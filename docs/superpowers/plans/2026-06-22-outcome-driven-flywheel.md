# Outcome-Driven Flywheel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two-tier eval flywheel — add `forced-inject` + `optional` agentic arms, measure the proxy↔outcome correlation, and harden the two metric bugs that bias the outcome signal — so retrieval optimizations are validated against real agent behavior.

**Architecture:** The cheap offline proxy (`sym_success@k`) is the inner loop; a 3-/4-arm agentic eval (`control` / `optional` / `forced-inject` / `mandatory-call`) is the outer loop. A new correlation module joins the proxy per task with per-arm grounded-success, and arm contrasts (`forced−control` = knowledge ceiling, `optional−control` = captured today, `forced−optional` = adoption tax) decompose the loop's failure modes.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, the existing `repo_atlas/eval/` harness (`ClaudeRunner`, `GroundingScorer`, `causal`, `aggregate`, `offline/`), driving `claude -p` headless.

**Spec:** `docs/superpowers/specs/2026-06-22-outcome-driven-flywheel-design.md`

**Conventions:** line-length 100, target py312, `from __future__ import annotations` at file top. `tests/` is gitignored — new test files MUST be `git add -f`. Run tests with `.venv/bin/python -m pytest <paths> -p no:cacheprovider` (pyproject sets `--cov`; append `--no-cov` if `pytest-cov` is absent).

---

## File Structure

- `repo_atlas/eval/extract.py` (modify) — gold-anchored extraction.
- `repo_atlas/eval/oracle.py` (modify) — source-grep existence fallback.
- `repo_atlas/eval/runner.py` (modify) — arm table, `format_injection`, `_build_cmd(inject_text)`, retriever wiring.
- `repo_atlas/eval/offline/retriever.py` (modify) — `kinds=` passthrough on `.retrieve`.
- `repo_atlas/eval/aggregate.py` (modify) — `MultiScorecard` + `aggregate_arms` + contrasts.
- `repo_atlas/eval/harness.py` (modify) — `run_arms` + `run_multi_eval`.
- `repo_atlas/eval/correlation.py` (create) — `compute_proxy` + `correlate`.
- `repo_atlas/eval/report.py` (modify) — `render_multi_scorecard`.
- `repo_atlas/cli.py` (modify) — `eval-arms` subcommand.

Each task is self-contained: a back-compatible default keeps existing callers/tests green until the wiring tasks land.

---

### Task 1: Gold-anchored extraction

**Files:**
- Modify: `repo_atlas/eval/extract.py`
- Test: `tests/test_eval_extract.py`

The `_is_symbol_ref` heuristic drops a lowercase non-call identifier, so a real `required_api` token can be a false grounded-miss. Add an exact-token pass anchored to the task's gold tokens.

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_extract.py`)

```python
def test_extract_includes_gold_token_the_heuristic_drops():
    diff = ("--- /dev/null\n+++ b/a.c\n@@ -0,0 +1 @@\n"
            "+    size_t n = arraysize;\n")
    syms, _ = extract_refs(diff)
    assert "arraysize" not in syms                       # lowercase, no call -> heuristic drops it
    syms2, _ = extract_refs(diff, gold_tokens=["arraysize"])
    assert "arraysize" in syms2                          # exact gold token anchored in

def test_extract_gold_token_qualified_is_bared():
    diff = "--- /dev/null\n+++ b/a.c\n@@ -0,0 +1 @@\n+  x = cgefoo;\n"
    syms, _ = extract_refs(diff, gold_tokens=["ns::cgefoo"])
    assert "cgefoo" in syms                               # qualifier stripped, bare token matched

def test_extract_gold_token_absent_not_added():
    diff = "--- /dev/null\n+++ b/a.c\n@@ -0,0 +1 @@\n+  x = 1;\n"
    syms, _ = extract_refs(diff, gold_tokens=["cgefoo"])
    assert "cgefoo" not in syms                           # gold token not present in diff -> not added
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_extract.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `extract_refs() got an unexpected keyword argument 'gold_tokens'`.

- [ ] **Step 3: Implement** — change the signature and add a gold-anchored pass that also tracks added line bodies.

```python
def extract_refs(diff: str, gold_tokens=()) -> tuple[list[str], list[str]]:
    """From a unified diff: (referenced symbol-like identifiers in added lines, touched files).

    `gold_tokens` (e.g. a task's required_apis/expected_symbols) are matched EXACTLY as whole
    words on added lines and included even when the `_is_symbol_ref` heuristic would drop them
    (a lowercase, non-call API). Qualified tokens are bared (`ns::foo` -> `foo`). This stops
    GroundingScorer from registering false misses on extractor noise. Order-preserving dedup."""
    files: dict[str, None] = {}
    symbols: dict[str, None] = {}
    added: list[str] = []
    for line in diff.splitlines():
        fm = _FILE.match(line)
        if fm:
            files[fm.group(1).strip()] = None
            continue
        if line.startswith("+") and not line.startswith("+++"):
            body = line[1:]
            added.append(body)
            for m in _IDENT.finditer(body):
                nxt = body[m.end():m.end() + 1]
                if _is_symbol_ref(m.group(), nxt):
                    symbols[m.group()] = None
    for g in gold_tokens:
        bare = g.split("::")[-1]
        if bare in symbols:
            continue
        pat = re.compile(r"\b" + re.escape(bare) + r"\b")
        if any(pat.search(b) for b in added):
            symbols[bare] = None
    return list(symbols), list(files)
```

- [ ] **Step 4: Run to verify pass** (all of `test_eval_extract.py`, incl. the existing 4 tests).

Run: `.venv/bin/python -m pytest tests/test_eval_extract.py -p no:cacheprovider --no-cov -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/extract.py
git add -f repo_atlas/eval/extract.py tests/test_eval_extract.py
git commit -m "feat(repo_atlas/eval): gold-anchored extraction — exact required_api tokens survive the heuristic"
```

---

### Task 2: Authoritative oracle (source-grep fallback)

**Files:**
- Modify: `repo_atlas/eval/oracle.py`
- Test: `tests/test_eval_oracle.py`

`store_exists_fn` is backed only by the atlas index, so an under-indexed-but-real symbol inflates `hallucination_rate`. Add a one-walk source token-set fallback before declaring a symbol non-existent.

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_oracle.py`)

```python
def test_store_exists_fn_source_fallback(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.cpp").write_text("void cgeRealThing() { /* impl */ }\n")
    st = Store(str(tmp_path / "b.db"))                    # empty store: nothing indexed
    exists = store_exists_fn(st, "r1", repo_path=str(src))
    assert exists("cgeRealThing") is True                # not indexed, but present in source
    assert exists("ns::cgeRealThing") is True            # qualified -> bared -> matched
    assert exists("cgeNope") is False                    # genuinely absent

def test_store_exists_fn_no_repo_path_is_index_only(tmp_path):
    st = Store(str(tmp_path / "c.db"))
    exists = store_exists_fn(st, "r1")                    # no fallback configured
    assert exists("cgeAnything") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_oracle.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `store_exists_fn() got an unexpected keyword argument 'repo_path'`.

- [ ] **Step 3: Implement** — replace the file contents.

```python
from __future__ import annotations

import os
import re
from typing import Callable

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SRC_EXT = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".java", ".kt",
            ".js", ".ts", ".jsx", ".tsx", ".py", ".go", ".rs", ".m", ".mm")
_SKIP_DIRS = {".git", "node_modules", "build", ".venv", "__pycache__", "dist"}


def _repo_tokens(repo_path: str) -> set:
    """Every identifier token in the repo's source files (one walk). Authoritative existence
    fallback for symbols the atlas index under-indexed. Unreadable files are skipped."""
    toks: set = set()
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if fn.endswith(_SRC_EXT):
                try:
                    with open(os.path.join(root, fn), errors="ignore") as fh:
                        toks.update(_IDENT.findall(fh.read()))
                except OSError:
                    pass
    return toks


def store_exists_fn(store, repo: str, repo_path: str | None = None) -> Callable[[str], bool]:
    """An exists_fn(symbol)->bool: the repo_atlas index, then (if `repo_path` given) the repo
    source token set as an authoritative fallback. Per-symbol results and the token set (built
    lazily, once) are cached for the eval run."""
    cache: dict[str, bool] = {}
    tokens: dict[str, set] = {}

    def exists(symbol: str) -> bool:
        if symbol not in cache:
            ok = store.symbols_exist(repo, [symbol])[symbol]
            if not ok and repo_path:
                if "t" not in tokens:
                    tokens["t"] = _repo_tokens(repo_path)
                ok = symbol.split("::")[-1] in tokens["t"]
            cache[symbol] = ok
        return cache[symbol]

    return exists
```

- [ ] **Step 4: Run to verify pass** (incl. the existing `test_store_exists_fn`).

Run: `.venv/bin/python -m pytest tests/test_eval_oracle.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/oracle.py
git add -f repo_atlas/eval/oracle.py tests/test_eval_oracle.py
git commit -m "feat(repo_atlas/eval): authoritative oracle — source-token fallback for under-indexed symbols"
```

---

### Task 3: Arm table + forced-injection formatting + `_build_cmd`

**Files:**
- Modify: `repo_atlas/eval/runner.py`
- Test: `tests/test_eval_runner.py`

Generalize the two hardcoded conditions into an arm table, add the prior-art formatter, and let `_build_cmd` take injected text. All pure/sync — no `claude` CLI needed.

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_runner.py`; add `format_injection` to the import line)

```python
def test_build_cmd_optional_wires_mcp_without_directive():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    cmd = r._build_cmd(t, "optional", "/work")
    prompt = cmd[cmd.index("-p") + 1]
    assert prompt == "do the thing"                       # NO directive prepended
    assert "find_related" not in prompt
    assert "--mcp-config" in cmd                          # tools available, agent may choose

def test_build_cmd_forced_inject_prepends_text_no_mcp():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    cmd = r._build_cmd(t, "forced-inject", "/work", inject_text="PRIOR ART: cgeFoo\n\n")
    prompt = cmd[cmd.index("-p") + 1]
    assert prompt.startswith("PRIOR ART: cgeFoo")
    assert "do the thing" in prompt
    assert "--mcp-config" not in cmd                      # knowledge injected; tools NOT wired

def test_build_cmd_control_is_bare_no_mcp():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    cmd = r._build_cmd(t, "control", "/work")
    assert cmd[cmd.index("-p") + 1] == "do the thing"
    assert "--mcp-config" not in cmd

def test_format_injection_caps_and_headers():
    units = [{"name": "cgeFoo", "file": "a.cpp", "text": "x " * 500},
             {"name": "cgeBar", "file": "b.cpp", "text": "does bar"}]
    out = format_injection(units, max_k=1, max_chars=20)
    assert out.startswith("Relevant prior art")
    assert "cgeFoo" in out and "cgeBar" not in out        # max_k=1 keeps only the top unit
    assert "x x x x x" in out and len(out) < 120          # snippet collapsed + char-capped

def test_format_injection_empty_is_blank():
    assert format_injection([]) == ""
```

Also confirm the existing back-compat tests still pass: `test_build_cmd_treatment_steers_and_wires_mcp` (treatment == `mandatory-call`) and `test_stub_runner_returns_canned` must remain green.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError: cannot import name 'format_injection'`.

- [ ] **Step 3: Implement** — add the formatter and arm table above `ClaudeRunner`, and rewrite `_build_cmd`.

Add after the `STEER` constant:

```python
INJECT_HEADER = "Relevant prior art in this codebase (reuse these instead of inventing):"


def format_injection(units: list, *, max_k: int = 5, max_chars: int = 400) -> str:
    """Render the top retrieval units as a prior-art block to PREPEND for the forced-inject arm.
    `units` are find_related_units dicts (file/name/text). Whitespace is collapsed and each
    snippet char-capped so the injected context stays bounded. Empty units -> "" (no header)."""
    rows = []
    for u in units[:max_k]:
        name = u.get("name") or u.get("qualified_name") or "?"
        path = u.get("file") or "?"
        snippet = " ".join((u.get("text") or "").split())[:max_chars]
        rows.append(f"- `{name}` ({path}): {snippet}")
    if not rows:
        return ""
    return INJECT_HEADER + "\n" + "\n".join(rows) + "\n\n"


# arm -> (wire_mcp, prompt_mode). prompt_mode: "bare" | "steer" | "inject".
# control/optional/forced-inject/mandatory-call are the canonical arms; baseline/treatment are
# retained as back-compat aliases for the legacy 2-condition harness + tests.
ARMS = {
    "control": (False, "bare"),
    "optional": (True, "bare"),
    "forced-inject": (False, "inject"),
    "mandatory-call": (True, "steer"),
    "baseline": (False, "bare"),
    "treatment": (True, "steer"),
}
```

Replace `_build_cmd`:

```python
    def _build_cmd(self, task: Task, condition: str, work: str, inject_text: str = "") -> list:
        """Construct the `claude -p` argv for an arm. control/baseline: bare prompt, no MCP.
        optional: bare prompt + MCP wired. forced-inject: prior-art prepended, NO MCP.
        mandatory-call/treatment: STEER directive prepended + MCP wired."""
        wire_mcp, mode = ARMS[condition]
        if mode == "steer":
            prompt = self._steer + task.prompt
        elif mode == "inject":
            prompt = inject_text + task.prompt
        else:
            prompt = task.prompt
        cmd = ["claude", "-p", prompt, "--output-format", "json",
               "--permission-mode", "acceptEdits", "--add-dir", work, "--model", self._model]
        if wire_mcp:
            cmd += ["--mcp-config", self._mcp, "--strict-mcp-config",
                    "--allowedTools", "mcp__repo-atlas__find_related",
                    "mcp__repo-atlas__prepare_change", "mcp__repo-atlas__verify_grounding",
                    "mcp__repo-atlas__list_repos"]
        return cmd
```

- [ ] **Step 4: Run to verify pass** (new + existing runner tests).

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -p no:cacheprovider --no-cov -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/runner.py
git add -f repo_atlas/eval/runner.py tests/test_eval_runner.py
git commit -m "feat(repo_atlas/eval): arm table + format_injection + inject_text in _build_cmd"
```

---

### Task 4: Wire retriever + gold-extract into `ClaudeRunner.run`

**Files:**
- Modify: `repo_atlas/eval/runner.py`
- Test: `tests/test_eval_runner.py`

Add an injected retriever, an async `_inject_text` helper, and thread gold tokens into `extract_refs`. `run()` itself stays integration-only (drives `claude`), so we test the new async helper directly with a stub retriever.

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_runner.py`)

```python
@pytest.mark.asyncio
async def test_inject_text_uses_retriever_for_forced_arm():
    from repo_atlas.eval.offline.retriever import StubRetriever
    sr = StubRetriever(hits_by_query={
        "do the thing": [{"name": "cgeFoo", "file": "a.cpp", "text": "foo helper"}]})
    r = ClaudeRunner({"gpuimage": "/x"}, "/m", retriever=sr)
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    txt = await r._inject_text(t)
    assert txt.startswith("Relevant prior art") and "cgeFoo" in txt

@pytest.mark.asyncio
async def test_inject_text_empty_without_retriever():
    r = ClaudeRunner({"gpuimage": "/x"}, "/m")             # no retriever wired
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="p", rubric="r")
    assert await r._inject_text(t) == ""
```

Note: `StubRetriever.retrieve(query, repo, k)` must accept the `kinds=` kwarg added in Task 7; for this task it is called without `kinds`, so the current signature is fine and the test passes independently.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py::test_inject_text_uses_retriever_for_forced_arm -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ClaudeRunner.__init__() got an unexpected keyword argument 'retriever'`.

- [ ] **Step 3: Implement** — extend `__init__`, add `_inject_text`, and update `run()`.

Update `__init__` (add the two params + assignments):

```python
    def __init__(self, repo_paths: dict, mcp_config_path: str,
                 model: str = "claude-sonnet-4-6", steer: str = STEER,
                 retriever=None, inject_k: int = 5):
        self._repo_paths = repo_paths           # repo name -> source path
        self._mcp = mcp_config_path
        self._model = model
        self._steer = steer
        self._retriever = retriever             # OfflineRetriever-like; used by forced-inject
        self._inject_k = inject_k
```

Add the helper (above `run`):

```python
    async def _inject_text(self, task: Task) -> str:
        """Forced-inject arm: retrieve prior art via the production path and format it. Returns
        "" when no retriever is wired (the arm then degrades to a bare-prompt control)."""
        if self._retriever is None:
            return ""
        units = await self._retriever.retrieve(task.prompt, task.repo, self._inject_k)
        return format_injection(units, max_k=self._inject_k)
```

In `run()`, compute the injection, pass it to `_build_cmd`, gate adoption telemetry on `wire_mcp`, and pass gold tokens to `extract_refs`:

```python
        wire_mcp, mode = ARMS[condition]
        inject = await self._inject_text(task) if mode == "inject" else ""
        try:
            # src (config) + work (mkdtemp) are trusted, not user input -> shell pipe is safe.
            subprocess.run(f"git -C {src} archive HEAD | tar -x -C {work}", shell=True, check=True)
            subprocess.run(["git", "-C", work, "init", "-q"], check=True)
            subprocess.run(["git", "-C", work, "add", "-A"], check=True)
            subprocess.run(["git", "-C", work, "-c", "user.email=e@x", "-c", "user.name=e",
                            "commit", "-qm", "base"], check=True)

            proc = subprocess.run(self._build_cmd(task, condition, work, inject), cwd=work,
                                  capture_output=True, text=True, timeout=900)
            raw = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
            diff = subprocess.run(["git", "-C", work, "diff", "HEAD"],
                                  capture_output=True, text=True).stdout
        finally:
            shutil.rmtree(work, ignore_errors=True)
        gold = list(task.required_apis) + list(task.expected_symbols)
        symbols, files = extract_refs(diff, gold_tokens=gold)
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        tokens = int(usage.get("output_tokens", 0)) + int(usage.get("input_tokens", 0))
        tool_calls = int(raw.get("num_turns", 0)) if isinstance(raw, dict) else 0  # proxy
        session_id = raw.get("session_id", "") if isinstance(raw, dict) else ""
        atlas_calls = _atlas_calls_for_session(session_id)
        queries, surfaced = [], False
        if wire_mcp:
            queries, fr_files = _find_related_files_for_session(session_id)
            surfaced = any(pf in set(fr_files) for pf in task.prior_art_files)
        return RunResult(condition, symbols, files, tool_calls, tokens, raw, diff, atlas_calls,
                         find_related_queries=queries, retrieval_surfaced_gold=surfaced)
```

(The `src`/`work` setup lines above `wire_mcp` are unchanged; only the body shown is edited.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -p no:cacheprovider --no-cov -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/runner.py
git add -f repo_atlas/eval/runner.py tests/test_eval_runner.py
git commit -m "feat(repo_atlas/eval): wire retriever + gold-anchored extract into ClaudeRunner.run"
```

---

### Task 5: Per-arm aggregate + contrasts

**Files:**
- Modify: `repo_atlas/eval/aggregate.py`
- Test: `tests/test_eval_aggregate.py`

Add a multi-arm scorecard alongside the existing pair-based one (which stays for the legacy `eval` command).

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_aggregate.py`)

```python
def _score(arm, success):
    from repo_atlas.eval.aggregate import TaskScore
    return TaskScore(task_id="t", condition=arm, success=success, hallucination_rate=0.0,
                     reuse_recall=0.0, exploration_cost=1, atlas_calls=(1 if arm == "optional" and success else 0),
                     retrieval_surfaced_gold=success)

def test_aggregate_arms_success_and_contrasts():
    from repo_atlas.eval.aggregate import aggregate_arms
    arms = ["control", "optional", "forced-inject"]
    per_task = {
        "t1": {"control": _score("control", False), "optional": _score("optional", False),
               "forced-inject": _score("forced-inject", True)},
        "t2": {"control": _score("control", False), "optional": _score("optional", True),
               "forced-inject": _score("forced-inject", True)},
    }
    sc = aggregate_arms(per_task, arms)
    assert sc.summary["n"] == 2
    assert sc.summary["success"]["control"] == 0.0
    assert sc.summary["success"]["optional"] == 0.5
    assert sc.summary["success"]["forced-inject"] == 1.0
    contrasts = sc.summary["contrasts"]
    assert contrasts["ceiling (forced−control)"] == 1.0          # 1.0 - 0.0
    assert contrasts["captured (optional−control)"] == 0.5       # 0.5 - 0.0
    assert contrasts["adoption_tax (forced−optional)"] == 0.5    # 1.0 - 0.5
    assert sc.summary["adoption_runs"]["optional"] == 1          # only the t2 optional success called tools
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_aggregate.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `cannot import name 'aggregate_arms'`.

- [ ] **Step 3: Implement** — append to `repo_atlas/eval/aggregate.py`.

```python
@dataclass
class MultiScorecard:
    per_task: dict          # task_id -> {arm -> TaskScore}
    arms: list              # arm order
    summary: dict


def aggregate_arms(per_task: dict, arms: list) -> MultiScorecard:
    """Per-arm grounded-success + the three loop-decomposing contrasts. `per_task` maps
    task_id -> {arm -> TaskScore}; arms missing from a task are skipped for that arm's mean."""
    by_arm = {a: [pt[a] for pt in per_task.values() if a in pt] for a in arms}
    succ = {a: _mean([1.0 if s.success else 0.0 for s in by_arm[a]]) for a in arms}
    summary = {
        "n": len(per_task),
        "success": succ,
        "adoption_runs": {a: sum(1 for s in by_arm[a] if s.atlas_calls > 0) for a in arms},
        "surfaced_rate": {a: _mean([1.0 if s.retrieval_surfaced_gold else 0.0 for s in by_arm[a]])
                          for a in arms},
        "contrasts": {},
    }
    if "forced-inject" in arms and "control" in arms:
        summary["contrasts"]["ceiling (forced−control)"] = succ["forced-inject"] - succ["control"]
    if "optional" in arms and "control" in arms:
        summary["contrasts"]["captured (optional−control)"] = succ["optional"] - succ["control"]
    if "forced-inject" in arms and "optional" in arms:
        summary["contrasts"]["adoption_tax (forced−optional)"] = succ["forced-inject"] - succ["optional"]
    return MultiScorecard(per_task, arms, summary)
```

- [ ] **Step 4: Run to verify pass** (incl. existing aggregate tests).

Run: `.venv/bin/python -m pytest tests/test_eval_aggregate.py -p no:cacheprovider --no-cov -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/aggregate.py
git add -f repo_atlas/eval/aggregate.py tests/test_eval_aggregate.py
git commit -m "feat(repo_atlas/eval): aggregate_arms — per-arm success + ceiling/captured/adoption-tax contrasts"
```

---

### Task 6: Multi-arm harness loop

**Files:**
- Modify: `repo_atlas/eval/harness.py`
- Test: `tests/test_eval_harness.py`

Reuse `_score` (unchanged) for every arm; add the loop + a resilient top-level runner. `StubRunner` already keys on `(task.id, condition)`, so arbitrary arm names work.

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_harness.py`)

```python
@pytest.mark.asyncio
async def test_run_multi_eval_per_arm_with_stubs():
    from repo_atlas.eval.harness import run_multi_eval
    from repo_atlas.eval.grounding_scorer import GroundingScorer
    task = Task(id="t1", kind="dev", repo="r1", prompt="p", rubric="x", required_apis=["cgeFoo"])
    runner = StubRunner({
        ("t1", "control"): RunResult("control", [], [], 5, 50, {}, "", 0),
        ("t1", "optional"): RunResult("optional", ["cgeFoo"], [], 4, 60, {}, "", 1),
        ("t1", "forced-inject"): RunResult("forced-inject", ["cgeFoo"], [], 3, 70, {}, "", 0),
    })
    arms = ["control", "optional", "forced-inject"]
    sc = await run_multi_eval([task], runner, arms, GroundingScorer(), lambda s: True)
    assert sc.summary["n"] == 1
    assert sc.summary["success"]["control"] == 0.0           # no required api in diff
    assert sc.summary["success"]["optional"] == 1.0          # referenced cgeFoo
    assert sc.summary["success"]["forced-inject"] == 1.0
    assert sc.summary["contrasts"]["adoption_tax (forced−optional)"] == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py::test_run_multi_eval_per_arm_with_stubs -p no:cacheprovider --no-cov -q`
Expected: FAIL — `cannot import name 'run_multi_eval'`.

- [ ] **Step 3: Implement** — append to `repo_atlas/eval/harness.py`.

```python
async def run_arms(task, runner, arms, judge, exists_fn: Callable[[str], bool]) -> dict:
    """Run one task across every arm; return {arm -> TaskScore}."""
    out = {}
    for arm in arms:
        run = await runner.run(task, condition=arm)
        out[arm] = await _score(task, run, judge=judge, exists_fn=exists_fn)
    return out


async def run_multi_eval(tasks, runner, arms, judge, exists_fn: Callable[[str], bool]):
    """Multi-arm agentic eval. A task whose run/judge raises is skipped (logged), so one bad
    run doesn't waste a long eval. Returns a MultiScorecard."""
    from repo_atlas.eval.aggregate import aggregate_arms
    per_task = {}
    for t in tasks:
        try:
            per_task[t.id] = await run_arms(t, runner, arms, judge, exists_fn)
        except Exception as exc:                       # noqa: BLE001 - resilience boundary
            print(f"[eval] task {t.id} failed, skipping: {type(exc).__name__}: {exc}")
    return aggregate_arms(per_task, arms)
```

- [ ] **Step 4: Run to verify pass** (incl. existing harness tests).

Run: `.venv/bin/python -m pytest tests/test_eval_harness.py -p no:cacheprovider --no-cov -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/harness.py
git add -f repo_atlas/eval/harness.py tests/test_eval_harness.py
git commit -m "feat(repo_atlas/eval): run_arms + run_multi_eval — multi-arm agentic loop"
```

---

### Task 7: Proxy↔outcome correlation

**Files:**
- Create: `repo_atlas/eval/correlation.py`
- Modify: `repo_atlas/eval/offline/retriever.py` (add `kinds=` passthrough)
- Test: `tests/test_eval_correlation.py` (create)

The proxy is the lap-6b doc-free symbol-rank check: is the task's `required_api` in the symbol-kind retrieval top-K. `correlate` joins it with per-arm grounded-success.

- [ ] **Step 1: Add `kinds=` to both retrievers** (so the proxy can request symbol-only retrieval; `find_related_units` already accepts `kinds`).

In `repo_atlas/eval/offline/retriever.py`, `OfflineRetriever.retrieve`:

```python
    async def retrieve(self, query: str, repo, k: int, kinds=None) -> list:
        import repo_atlas.retrieve as _r          # late import so monkeypatch targets the module
        repos = [repo] if repo else None
        return await _r.find_related_units(self._store, self._embedder, query,
                                           repos=repos, k=k, kinds=kinds)
```

and `StubRetriever.retrieve`:

```python
    async def retrieve(self, query: str, repo, k: int, kinds=None) -> list:
        return list(self._hits.get(query, []))[:k]
```

- [ ] **Step 2: Write the failing test** (`tests/test_eval_correlation.py`)

```python
import pytest
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.offline.retriever import StubRetriever
from repo_atlas.eval.aggregate import TaskScore, aggregate_arms
from repo_atlas.eval.correlation import compute_proxy, correlate


def _ts(arm, success):
    return TaskScore(task_id="x", condition=arm, success=success, hallucination_rate=0.0,
                     reuse_recall=0.0, exploration_cost=1)


@pytest.mark.asyncio
async def test_compute_proxy_surfaced_when_required_api_in_symbol_hits():
    t1 = Task(id="t1", kind="dev", repo="r", prompt="make a blend", rubric="x",
              required_apis=["cgeFoo"])
    t2 = Task(id="t2", kind="dev", repo="r", prompt="scale a buffer", rubric="x",
              required_apis=["cgeBar"])
    sr = StubRetriever(hits_by_query={
        "make a blend": [{"name": "cgeFoo", "file": "a.cpp", "text": ""}],
        "scale a buffer": [{"name": "cgeOther", "file": "b.cpp", "text": ""}]})
    proxy = await compute_proxy([t1, t2], sr, k=10)
    assert proxy == {"t1": True, "t2": False}


def test_correlate_conditional_success_rates():
    per_task = {
        "t1": {"optional": _ts("optional", True)},     # proxy surfaced, succeeded
        "t2": {"optional": _ts("optional", False)},    # proxy missed, failed
        "t3": {"optional": _ts("optional", False)},    # proxy surfaced, failed
    }
    sc = aggregate_arms(per_task, ["optional"])
    proxy = {"t1": True, "t2": False, "t3": True}
    cr = correlate(proxy, sc, "optional")
    assert cr["n_surfaced"] == 2 and cr["n_unsurfaced"] == 1
    assert cr["success_if_surfaced"] == 0.5            # t1 yes, t3 no
    assert cr["success_if_not"] == 0.0                 # t2 no
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_correlation.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `No module named 'repo_atlas.eval.correlation'`.

- [ ] **Step 4: Implement** — create `repo_atlas/eval/correlation.py`.

```python
from __future__ import annotations


async def compute_proxy(tasks, retriever, *, k: int = 10) -> dict:
    """Per-task offline proxy signal: is the task's required_api in the SYMBOL-kind retrieval
    top-K (the lap-6b doc-free symbol-rank check). Tasks with no required_apis -> False.
    `retriever.retrieve(query, repo, k, kinds=...)` returns find_related units."""
    out = {}
    for t in tasks:
        surfaced = False
        if t.required_apis:
            hits = await retriever.retrieve(t.prompt, t.repo, k, kinds=["symbol"])
            names = {h.get("name") for h in hits} | {h.get("qualified_name") for h in hits}
            surfaced = any(api in names or api.split("::")[-1] in names
                           for api in t.required_apis)
        out[t.id] = surfaced
    return out


def correlate(proxy_by_task: dict, scorecard, arm: str) -> dict:
    """For one arm: grounded-success rate conditioned on whether the proxy surfaced the API.
    `None` rate when a bucket is empty. Directional only at small N."""
    yes = [pt[arm] for tid, pt in scorecard.per_task.items()
           if arm in pt and proxy_by_task.get(tid)]
    no = [pt[arm] for tid, pt in scorecard.per_task.items()
          if arm in pt and not proxy_by_task.get(tid)]

    def rate(xs):
        return sum(1 for s in xs if s.success) / len(xs) if xs else None

    return {"arm": arm, "n_surfaced": len(yes), "n_unsurfaced": len(no),
            "success_if_surfaced": rate(yes), "success_if_not": rate(no)}
```

- [ ] **Step 5: Run to verify pass** (correlation + the retriever-touching offline tests).

Run: `.venv/bin/python -m pytest tests/test_eval_correlation.py tests/test_offline_gen_grounding.py -p no:cacheprovider --no-cov -q`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/correlation.py repo_atlas/eval/offline/retriever.py
git add -f repo_atlas/eval/correlation.py repo_atlas/eval/offline/retriever.py tests/test_eval_correlation.py
git commit -m "feat(repo_atlas/eval): proxy↔outcome correlation (compute_proxy + correlate) + kinds passthrough"
```

---

### Task 8: Multi-arm report

**Files:**
- Modify: `repo_atlas/eval/report.py`
- Test: `tests/test_eval_report.py`

Add `render_multi_scorecard` next to the existing `render_scorecard` (`_pct` is reused).

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_report.py`)

```python
def test_render_multi_scorecard_has_arms_contrasts_and_correlation():
    from repo_atlas.eval.aggregate import TaskScore, aggregate_arms
    from repo_atlas.eval.report import render_multi_scorecard

    def ts(arm, ok):
        return TaskScore(task_id="t", condition=arm, success=ok, hallucination_rate=0.0,
                         reuse_recall=0.0, exploration_cost=1)
    per_task = {"t1": {"control": ts("control", False), "optional": ts("optional", False),
                       "forced-inject": ts("forced-inject", True)}}
    sc = aggregate_arms(per_task, ["control", "optional", "forced-inject"])
    corrs = [{"arm": "optional", "n_surfaced": 1, "n_unsurfaced": 0,
              "success_if_surfaced": 0.0, "success_if_not": None}]
    md = render_multi_scorecard(sc, corrs)
    assert "forced-inject" in md and "control" in md
    assert "Arm contrasts" in md and "adoption_tax" in md
    assert "directional only" in md                      # N caveat is explicit
    assert "—" in md                                     # None bucket renders as a dash
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_report.py::test_render_multi_scorecard_has_arms_contrasts_and_correlation -p no:cacheprovider --no-cov -q`
Expected: FAIL — `cannot import name 'render_multi_scorecard'`.

- [ ] **Step 3: Implement** — append to `repo_atlas/eval/report.py`.

```python
def render_multi_scorecard(scorecard, correlations=None) -> str:
    """Markdown for the multi-arm outcome-driven eval: per-arm grounded-success, the loop
    contrasts, and (optional) the proxy↔outcome correlation with an explicit small-N caveat."""
    s = scorecard.summary
    arms = scorecard.arms
    lines = ["# repo_atlas eval — multi-arm (outcome-driven)\n",
             f"Tasks: **{s['n']}**  ·  arms: {', '.join(arms)}\n",
             "| arm | grounded-success | adoption (runs) | surfaced |",
             "|---|---|---|---|"]
    for a in arms:
        lines.append(f"| {a} | {_pct(s['success'][a])} | "
                     f"{s['adoption_runs'][a]}/{s['n']} | {_pct(s['surfaced_rate'][a])} |")
    lines.append("\n## Arm contrasts")
    for label, val in s["contrasts"].items():
        lines.append(f"- **{label}**: {val * 100:+.0f}pp")
    if correlations:
        lines += ["\n## Proxy → outcome correlation",
                  f"_N={s['n']}, directional only (small sample)._\n",
                  "| arm | success if surfaced | success if not | n surfaced/not |",
                  "|---|---|---|---|"]
        for cr in correlations:
            sif = "—" if cr["success_if_surfaced"] is None else _pct(cr["success_if_surfaced"])
            nif = "—" if cr["success_if_not"] is None else _pct(cr["success_if_not"])
            lines.append(f"| {cr['arm']} | {sif} | {nif} | "
                         f"{cr['n_surfaced']}/{cr['n_unsurfaced']} |")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass** (incl. existing report tests).

Run: `.venv/bin/python -m pytest tests/test_eval_report.py -p no:cacheprovider --no-cov -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/eval/report.py
git add -f repo_atlas/eval/report.py tests/test_eval_report.py
git commit -m "feat(repo_atlas/eval): render_multi_scorecard — per-arm + contrasts + correlation block"
```

---

### Task 9: CLI `eval-arms` subcommand

**Files:**
- Modify: `repo_atlas/cli.py`
- Test: `tests/test_eval_cli.py`

Wire it all: one `OfflineRetriever` feeds both forced-injection and the proxy; the oracle gets `repo_path` for the source fallback. The full run is integration-only (needs `claude` + a built index); the test covers argparse wiring.

- [ ] **Step 1: Write the failing test** (append to `tests/test_eval_cli.py`)

```python
def test_eval_arms_parser():
    args = cli.build_parser().parse_args(
        ["eval-arms", "--tasks", "/t", "--arms", "control,forced-inject", "--proxy-k", "8"])
    assert args.cmd == "eval-arms"
    assert args.tasks == "/t"
    assert args.arms == "control,forced-inject"
    assert args.proxy_k == 8
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_cli.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — argparse exits (`invalid choice: 'eval-arms'`).

- [ ] **Step 3: Implement** — add the parser, dispatch branch, and runner.

In `build_parser`, after the `eval-offline` parser block (before `return p`):

```python
    ea = sub.add_parser("eval-arms",
                        help="multi-arm agentic eval + proxy↔outcome correlation")
    ea.add_argument("--tasks", required=True, help="dir of task .toml files")
    ea.add_argument("--out", default="eval-arms-scorecard.md")
    ea.add_argument("--limit", type=int, default=0, help="limit number of tasks (0 = all)")
    ea.add_argument("--mcp-config", help="MCP config json (optional/mandatory-call arms)")
    ea.add_argument("--arms", default="control,optional,forced-inject,mandatory-call",
                    help="comma-separated arm names")
    ea.add_argument("--proxy-k", type=int, default=10, help="symbol-retrieval cutoff for the proxy")
```

In the dispatch function, after the `eval-offline` branch:

```python
    if args.cmd == "eval-arms":
        return _run_eval_arms(args)
```

Add `_run_eval_arms` (next to `_run_eval`):

```python
def _run_eval_arms(args) -> int:
    from repo_atlas.config import load_config
    from repo_atlas.store import Store
    from repo_atlas.embed import GatewayEmbedder
    from repo_atlas.eval.tasks import load_tasks
    from repo_atlas.eval.runner import ClaudeRunner
    from repo_atlas.eval.grounding_scorer import GroundingScorer
    from repo_atlas.eval.oracle import store_exists_fn
    from repo_atlas.eval.harness import run_multi_eval
    from repo_atlas.eval.correlation import compute_proxy, correlate
    from repo_atlas.eval.offline.retriever import OfflineRetriever
    from repo_atlas.eval.report import render_multi_scorecard
    from repo_atlas.registry import load_registry

    cfg = load_config(os.environ)
    tasks = load_tasks(args.tasks)
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        print(f"repo_atlas eval-arms: no tasks in {args.tasks}")
        return 2
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    registry = {e.name: e.repo_path
                for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    retriever = OfflineRetriever(store, embedder)
    runner = ClaudeRunner(registry, args.mcp_config or "", retriever=retriever)
    oracles = {name: store_exists_fn(store, name, repo_path=registry[name]) for name in registry}

    def exists(sym: str) -> bool:
        return any(o(sym) for o in oracles.values())

    sc = asyncio.run(run_multi_eval(tasks, runner, arms, GroundingScorer(), exists))
    proxy = asyncio.run(compute_proxy(tasks, retriever, k=args.proxy_k))
    corrs = [correlate(proxy, sc, a) for a in arms]
    md = render_multi_scorecard(sc, corrs)
    with open(args.out, "w") as fh:
        fh.write(md)
    print(md)
    print(f"\nwrote {args.out}")
    return 0
```

(If `asyncio` is not already imported at module scope in `cli.py`, add `import asyncio` at the top — `_run_index`/`_run_eval` already use `asyncio.run`, so it should be present.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_eval_cli.py -p no:cacheprovider --no-cov -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check repo_atlas/cli.py
git add -f repo_atlas/cli.py tests/test_eval_cli.py
git commit -m "feat(repo_atlas/eval): eval-arms CLI — 3-arm agentic + proxy↔outcome correlation"
```

---

### Task 10: Full-suite gate + integration smoke

**Files:** none (verification only).

- [ ] **Step 1: Run the whole eval test suite**

Run: `.venv/bin/python -m pytest tests/ -k "eval or offline or correlation" -p no:cacheprovider --no-cov -q`
Expected: PASS — no regressions in the legacy pair-based path (`test_eval_*`) or the new multi-arm path.

- [ ] **Step 2: Lint + type-check the touched modules**

```bash
.venv/bin/ruff check repo_atlas/eval/ repo_atlas/cli.py
.venv/bin/black --check repo_atlas/eval/ repo_atlas/cli.py
```
Expected: clean (config is line-length 100, py312).

- [ ] **Step 3: (integration, manual — needs `claude` CLI + a built index)** Smoke one repo, two arms, two tasks:

```bash
REPO_ATLAS_REGISTRY=atlas.toml .venv/bin/codewiki-atlas eval-arms \
  --tasks repo_atlas/eval/tasks-grounding --arms control,forced-inject \
  --limit 2 --out /tmp/arms-smoke.md --mcp-config /path/to/mcp.json
```
Expected: a scorecard with per-arm grounded-success, the `ceiling (forced−control)` contrast, and the proxy→outcome block. (Confirm the binary name against `pyproject.toml [project.scripts]`; the module entry is `python -m repo_atlas eval-arms ...`.)

- [ ] **Step 4: Final commit (if any formatting changed)**

```bash
git add -f repo_atlas/eval/ repo_atlas/cli.py tests/
git commit -m "chore(repo_atlas/eval): format + full-suite green for outcome-driven flywheel" || echo "nothing to commit"
```

---

## Self-Review

- **Spec coverage:** arms (T3/T4), forced-injection via `find_related_units` (T3/T4/T9), proxy↔outcome correlation + arm contrasts (T5/T7/T8), gold-anchored extraction (T1), authoritative oracle (T2), report (T8), CLI (T9). Deferred items (adoption-driving levers, transcript-aware reuse, N expansion, functional scoring) are correctly absent.
- **Type consistency:** `MultiScorecard.per_task` is `{task_id: {arm: TaskScore}}` everywhere (T5 defines, T6 produces, T7/T8 consume). `format_injection`/`_inject_text`/`_build_cmd(inject_text=...)` signatures match across T3/T4. `retrieve(query, repo, k, kinds=None)` is consistent across `OfflineRetriever`/`StubRetriever`/`compute_proxy` (T7). `store_exists_fn(store, repo, repo_path=None)` consistent T2/T9.
- **Back-compat:** every modified function keeps a default that leaves existing callers/tests green (`gold_tokens=()`, `repo_path=None`, `inject_text=""`, `baseline`/`treatment` aliases, `kinds=None`); the legacy `eval` command and its `run_pair`/`render_scorecard` path are untouched.
- **No placeholders:** every code step is complete and runnable.
