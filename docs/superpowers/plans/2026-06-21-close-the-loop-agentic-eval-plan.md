# Close-the-Loop Mechanism-Resolved Agentic Eval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-task causal-chain tracing to the agentic eval (retrieval-surfaced-gold → reused → outcome), curate ~11 fresh harder intra-repo prior-art tasks, and run baseline-vs-improved-treatment to validate that better retrieval helps a real coding agent.

**Architecture:** Per `docs/superpowers/specs/2026-06-21-close-the-loop-agentic-eval-design.md`. Extends `repo_atlas/eval/` (Task / RunResult / harness / aggregate / report) + a new `causal.py`. Reuses the existing `ClaudeRunner` (forced directive + session capture + adoption telemetry), `GatewayJudge`, and the `/home/vinc/repo-atlas-eval-full/` run setup (atlas.db, atlas.toml, mcp.json).

**Tech Stack:** Python 3.12, pytest. Run env identical to prior agentic runs (local Ollama bge-m3 for the treatment server's find_related; gateway deepseek-chat judge).

**Conventions:**
- Run tests: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest <file> -m "not integration" -p no:cacheprovider --no-cov -q`
- `tests/` is gitignored → `git add -f`. `from __future__ import annotations`; line length 100.

---

## Task 1: `Task.prior_art_files`

**Files:**
- Modify: `repo_atlas/eval/tasks.py`
- Test: `tests/test_eval_priorart.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_priorart.py
import tomllib  # noqa: F401
from repo_atlas.eval.tasks import Task, load_tasks


def test_task_has_prior_art_default():
    t = Task(id="t", kind="dev", repo="r", prompt="p", rubric="x")
    assert t.prior_art_files == []


def test_load_tasks_reads_prior_art(tmp_path):
    (tmp_path / "a.toml").write_text(
        'id="t1"\nkind="dev"\nrepo="r"\nprompt="p"\nrubric="x"\n'
        'prior_art_files=["src/foo.h","src/foo.cpp"]\n')
    t = load_tasks(str(tmp_path))[0]
    assert t.prior_art_files == ["src/foo.h", "src/foo.cpp"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_priorart.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `TypeError`/`AttributeError` (no `prior_art_files`).

- [ ] **Step 3: Implement in `repo_atlas/eval/tasks.py`**

Add the field to the dataclass (after `expected_files`):
```python
    prior_art_files: list = field(default_factory=list)
```
In `load_tasks`, add to the `Task(...)` kwargs:
```python
            prior_art_files=list(d.get("prior_art_files", [])),
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_priorart.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
git add repo_atlas/eval/tasks.py
git add -f tests/test_eval_priorart.py
git commit -m "feat(repo_atlas/eval): Task.prior_art_files (mechanism-scoring gold)"
```

---

## Task 2: Mechanism capture in the runner

**Files:**
- Modify: `repo_atlas/eval/runner.py`
- Test: `tests/test_eval_mechanism.py`

- [ ] **Step 1: Write the failing test (the transcript extractor)**

```python
# tests/test_eval_mechanism.py
import json
from repo_atlas.eval.runner import _collect_files, RunResult


def test_collect_files_walks_buckets_and_json_strings():
    out = set()
    # structured envelope
    _collect_files({"result": {"docs": [{"file": "d.md"}],
                               "symbols": [{"file": "s.h"}, {"file": "s.cpp"}]}}, out)
    # a tool_result content that is a JSON *string*
    _collect_files(json.dumps({"result": {"symbols": [{"file": "x.h"}]}}), out)
    assert out == {"d.md", "s.h", "s.cpp", "x.h"}


def test_collect_files_ignores_non_files():
    out = set()
    _collect_files({"query": "no files here", "score": 0.5}, out)
    assert out == set()


def test_runresult_mechanism_defaults():
    r = RunResult("baseline", [], [], 0, 0, {}, "")
    assert r.find_related_queries == [] and r.retrieval_surfaced_gold is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_mechanism.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError: cannot import name '_collect_files'`.

- [ ] **Step 3: Implement in `repo_atlas/eval/runner.py`**

Add the two new `RunResult` fields (after `atlas_calls`):
```python
    find_related_queries: list = field(default_factory=list)
    retrieval_surfaced_gold: bool = False
```

Add these helpers (next to `_atlas_calls_for_session`):
```python
def _collect_files(obj, out: set) -> None:
    """Recursively collect every 'file' string value in a (possibly JSON-string-encoded)
    find_related result envelope ({result:{docs:[...],symbols:[...]}})."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "file" and isinstance(v, str):
                out.add(v)
            else:
                _collect_files(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _collect_files(x, out)
    elif isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                _collect_files(json.loads(s), out)
            except json.JSONDecodeError:
                pass


def _find_related_files_for_session(session_id: str) -> tuple:
    """From a session transcript: (find_related query strings, files returned by find_related)."""
    if not session_id:
        return [], []
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    if not hits:
        return [], []
    queries, use_ids, results, files = [], set(), {}, set()
    for line in open(hits[0]):
        if "find_related" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (obj.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "mcp__repo-atlas__find_related":
                q = (b.get("input") or {}).get("query")
                if q:
                    queries.append(q)
                use_ids.add(b.get("id"))
            elif b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = b.get("content")
    for uid in use_ids:
        if uid in results:
            _collect_files(results[uid], files)
    return queries, sorted(files)
```

In `ClaudeRunner.run`, replace the final `atlas_calls = ...` line and the `return` with:
```python
        atlas_calls = _atlas_calls_for_session(session_id)
        queries, surfaced = [], False
        if condition == "treatment":
            queries, fr_files = _find_related_files_for_session(session_id)
            surfaced = any(pf in set(fr_files) for pf in task.prior_art_files)
        return RunResult(condition, symbols, files, tool_calls, tokens, raw, diff, atlas_calls,
                         find_related_queries=queries, retrieval_surfaced_gold=surfaced)
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_mechanism.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/eval/runner.py
git add repo_atlas/eval/runner.py
git add -f tests/test_eval_mechanism.py
git commit -m "feat(repo_atlas/eval): capture find_related queries + retrieval_surfaced_gold from treatment transcript"
```

---

## Task 3: Causal classifier

**Files:**
- Create: `repo_atlas/eval/causal.py`
- Test: `tests/test_eval_causal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_causal.py
from repo_atlas.eval.causal import classify


def test_causal_win():
    assert classify(b=False, t=True, surfaced=True, reused=True, adopted=True) == "causal-win"


def test_win_unattributed():
    assert classify(b=False, t=True, surfaced=False, reused=False, adopted=True) == "win-unattributed"


def test_regression():
    assert classify(b=True, t=False, surfaced=True, reused=True, adopted=True) == "regression"


def test_surfaced_ignored():
    assert classify(b=True, t=True, surfaced=True, reused=False, adopted=True) == "surfaced-ignored"


def test_retrieval_miss():
    assert classify(b=False, t=False, surfaced=False, reused=False, adopted=True) == "retrieval-miss"


def test_no_effect():
    assert classify(b=True, t=True, surfaced=False, reused=False, adopted=False) == "no-effect"
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_causal.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `repo_atlas/eval/causal.py`**

```python
from __future__ import annotations

CATEGORIES = ("causal-win", "win-unattributed", "regression",
              "surfaced-ignored", "retrieval-miss", "no-effect")


def classify(*, b: bool, t: bool, surfaced: bool, reused: bool, adopted: bool) -> str:
    """Per-task causal category (first match wins). See the design spec for the taxonomy.
    b/t = baseline/treatment success; surfaced/reused/adopted are treatment-side signals."""
    if t and not b and surfaced and reused:
        return "causal-win"
    if t and not b:
        return "win-unattributed"
    if b and not t:
        return "regression"
    if surfaced and not reused:
        return "surfaced-ignored"
    if adopted and not surfaced:
        return "retrieval-miss"
    return "no-effect"
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_causal.py -p no:cacheprovider --no-cov -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/causal.py
git add -f tests/test_eval_causal.py
git commit -m "feat(repo_atlas/eval): causal classifier (causal-win / surfaced-ignored / retrieval-miss / ...)"
```

---

## Task 4: Thread mechanism through scoring, aggregation, report

**Files:**
- Modify: `repo_atlas/eval/aggregate.py` (TaskScore fields, PairResult.category, make_pair, aggregate)
- Modify: `repo_atlas/eval/harness.py` (`_score` passes mechanism signals)
- Modify: `repo_atlas/eval/report.py` (Mechanism section)
- Modify (if they break): `tests/test_eval_aggregate.py`, `tests/test_eval_report.py`, `tests/test_eval_harness.py`
- Test: add a case to `tests/test_eval_aggregate.py`

- [ ] **Step 1: Write the failing test (add to `tests/test_eval_aggregate.py`)**

```python
def test_aggregate_classifies_and_counts_mechanism():
    from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate
    base = TaskScore("t1", "baseline", success=False, hallucination_rate=0.0,
                     reuse_recall=0.0, exploration_cost=10)
    treat = TaskScore("t1", "treatment", success=True, hallucination_rate=0.0,
                      reuse_recall=0.0, exploration_cost=8, atlas_calls=2,
                      retrieval_surfaced_gold=True, reused_prior_art=True)
    sc = aggregate([make_pair("t1", base, treat)])
    assert sc.pairs[0].category == "causal-win"
    assert sc.summary["causal_wins"] == 1
    assert sc.summary["categories"]["causal-win"] == 1
    assert sc.summary["surfaced_rate"] == 1.0 and sc.summary["reused_rate"] == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_aggregate.py::test_aggregate_classifies_and_counts_mechanism -p no:cacheprovider --no-cov -q`
Expected: FAIL — `TypeError` (TaskScore has no `retrieval_surfaced_gold`) / missing `category`.

- [ ] **Step 3: Implement in `repo_atlas/eval/aggregate.py`**

Add a top-level import (after `from dataclasses import dataclass`):
```python
from repo_atlas.eval.causal import classify, CATEGORIES
```
(no circular import — `causal.py` imports nothing from `eval`.)

Add fields to `TaskScore` (after `atlas_calls`):
```python
    retrieval_surfaced_gold: bool = False
    reused_prior_art: bool = False
```
Add `category` to `PairResult` (after `regressed`):
```python
    category: str = ""
```
In `make_pair`, after computing `regressed`, classify and pass it:
```python
    category = classify(b=baseline.success, t=treatment.success,
                        surfaced=treatment.retrieval_surfaced_gold,
                        reused=treatment.reused_prior_art, adopted=treatment.atlas_calls > 0)
    return PairResult(task_id, baseline, treatment, regressed, category)
```
In `aggregate`, add to `summary` (before the `success_delta` line):
```python
        "causal_wins": sum(1 for p in pairs if p.category == "causal-win"),
        "categories": {c: sum(1 for p in pairs if p.category == c) for c in CATEGORIES},
        "surfaced_rate": _mean([1.0 if s.retrieval_surfaced_gold else 0.0 for s in t]),
        "reused_rate": _mean([1.0 if s.reused_prior_art else 0.0 for s in t]),
```

- [ ] **Step 4: Implement in `repo_atlas/eval/harness.py`**

In `_score`, add `reused_prior_art` + `retrieval_surfaced_gold` to the `TaskScore(...)` call:
```python
        atlas_calls=run.atlas_calls,
        retrieval_surfaced_gold=run.retrieval_surfaced_gold,
        reused_prior_art=any(pf in run.touched_files for pf in task.prior_art_files))
```

- [ ] **Step 5: Implement the Mechanism section in `repo_atlas/eval/report.py`**

In `render_scorecard`, after the per-task table (before the verdict), append:
```python
    cats = s.get("categories", {})
    lines += ["\n## Mechanism (causal trace)",
              f"**Causal wins (surfaced + reused + beat baseline): {s.get('causal_wins', 0)}/{s['n']}**  "
              f"· surfaced {s.get('surfaced_rate', 0)*100:.0f}% · reused {s.get('reused_rate', 0)*100:.0f}%\n",
              "| category | count |", "|---|---|"]
    lines += [f"| {c} | {n} |" for c, n in cats.items() if n]
    lines += ["\n| task | success b→t | surfaced | reused | category |",
              "|---|---|---|---|---|"]
    for p in scorecard.pairs:
        lines.append(f"| {p.task_id} | {p.baseline.success}→{p.treatment.success} | "
                     f"{'Y' if p.treatment.retrieval_surfaced_gold else '·'} | "
                     f"{'Y' if p.treatment.reused_prior_art else '·'} | {p.category} |")
```

- [ ] **Step 6: Run the eval test suite (new + existing)**

Run:
```bash
/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest \
  tests/test_eval_aggregate.py tests/test_eval_harness.py tests/test_eval_report.py \
  tests/test_eval_causal.py tests/test_eval_mechanism.py tests/test_eval_priorart.py \
  -m "not integration" -p no:cacheprovider --no-cov -q
```
Expected: PASS. If an existing aggregate/report/harness test fails because of the added fields/section, update only the broken assertion to accommodate the new (additive) keys/fields — do NOT weaken the new behavior.

- [ ] **Step 7: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/eval/aggregate.py repo_atlas/eval/harness.py repo_atlas/eval/report.py
git add repo_atlas/eval/aggregate.py repo_atlas/eval/harness.py repo_atlas/eval/report.py
git add -f tests/test_eval_aggregate.py tests/test_eval_report.py tests/test_eval_harness.py
git commit -m "feat(repo_atlas/eval): thread mechanism (surfaced/reused) -> causal category + Mechanism scorecard section"
```

---

## Task 5: Curate ~11 fresh hard-prior-art tasks

**Files:**
- Create: `repo_atlas/eval/tasks-closeloop/*.toml` (11 tasks)

All `prior_art_files` below are grep-verified to exist. Tasks are FRESH (≠ the 6 existing, ≠ the
15 offline cases). Each prompt names the *concept* of an existing pattern but not its file path, so
the agent must locate it (where find_related helps).

- [ ] **Step 1: Create the 5 gpuimage tasks**

```toml
# repo_atlas/eval/tasks-closeloop/cl-gpuimage-lut.toml
id = "cl-gpuimage-lut"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Add a CGE native filter that color-grades an image by mapping each pixel through a square lookup-table (LUT) image, following the existing lookup-table filter implementation in the CGE filter library."
rubric = "A correct solution adds a filter that loads a LUT texture and samples it per-pixel, following the existing cgeLookupFilter pattern."
prior_art_files = ["library/src/main/jni/cge/filters/cgeLookupFilter.h", "library/src/main/jni/cge/filters/cgeLookupFilter.cpp"]
expected_files = ["library/src/main/jni/cge/filters/cgeLookupFilter.h"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-gpuimage-sketch.toml
id = "cl-gpuimage-sketch"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Add a CGE native filter that produces a grayscale pencil-sketch effect using an edge/convolution kernel, following the existing emboss/edge filter implementation."
rubric = "A correct solution adds a convolution-kernel filter following the existing cgeEmbossFilter pattern."
prior_art_files = ["library/src/main/jni/cge/filters/cgeEmbossFilter.h", "library/src/main/jni/cge/filters/cgeEmbossFilter.cpp"]
expected_files = ["library/src/main/jni/cge/filters/cgeEmbossFilter.h"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-gpuimage-tonecurve.toml
id = "cl-gpuimage-tonecurve"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Add a CGE native filter that remaps image tones via a user-supplied control-point curve (tone curve), following the existing curve-adjustment filter."
rubric = "A correct solution adds a tone-curve filter following the existing cgeCurveAdjust pattern."
prior_art_files = ["library/src/main/jni/cge/filters/cgeCurveAdjust.h", "library/src/main/jni/cge/filters/cgeCurveAdjust.cpp"]
expected_files = ["library/src/main/jni/cge/filters/cgeCurveAdjust.h"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-gpuimage-multiply-blend.toml
id = "cl-gpuimage-multiply-blend"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Add a 'multiply' blend mode that combines two textures to the CGE native blend filter, following the existing blend filter implementation."
rubric = "A correct solution extends/follows the existing cgeBlendFilter implementation to add a multiply blend mode."
prior_art_files = ["library/src/main/jni/cge/filters/cgeBlendFilter.h", "library/src/main/jni/cge/filters/cgeBlendFilter.cpp"]
expected_files = ["library/src/main/jni/cge/filters/cgeBlendFilter.h"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-gpuimage-jni-version.toml
id = "cl-gpuimage-jni-version"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Expose a new native method that returns the CGE library version string to the Java layer, registered the same way as the existing native methods."
rubric = "A correct solution registers a new JNI method following the existing native-method registration in the CGE native bridge."
prior_art_files = ["library/src/main/jni/interface/cgeNativeLibrary.cpp", "library/src/main/jni/interface/cgeNativeLibrary.h"]
expected_files = ["library/src/main/jni/interface/cgeNativeLibrary.cpp"]
```

- [ ] **Step 2: Create the 4 libxcam tasks**

```toml
# repo_atlas/eval/tasks-closeloop/cl-libxcam-boxblur.toml
id = "cl-libxcam-boxblur"
kind = "dev"
repo = "libxcam"
prompt = "Add an OpenCL image handler to libxcam that applies a box blur, following the existing Gaussian blur handler in the ocl module."
rubric = "A correct solution adds an OpenCL handler following the existing cl_gauss_handler pattern."
prior_art_files = ["modules/ocl/cl_gauss_handler.h", "modules/ocl/cl_gauss_handler.cpp"]
expected_files = ["modules/ocl/cl_gauss_handler.h"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-libxcam-tonemap.toml
id = "cl-libxcam-tonemap"
kind = "dev"
repo = "libxcam"
prompt = "Add an OpenCL image handler that performs local-contrast tone mapping, following the existing retinex handler implementation."
rubric = "A correct solution adds an OpenCL handler following the existing cl_retinex_handler pattern."
prior_art_files = ["modules/ocl/cl_retinex_handler.h", "modules/ocl/cl_retinex_handler.cpp"]
expected_files = ["modules/ocl/cl_retinex_handler.h"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-libxcam-denoise.toml
id = "cl-libxcam-denoise"
kind = "dev"
repo = "libxcam"
prompt = "Add an OpenCL image handler that applies spatial-domain denoising, following the existing 3D denoise handler."
rubric = "A correct solution adds an OpenCL handler following the existing cl_3d_denoise_handler pattern."
prior_art_files = ["modules/ocl/cl_3d_denoise_handler.h", "modules/ocl/cl_3d_denoise_handler.cpp"]
expected_files = ["modules/ocl/cl_3d_denoise_handler.h"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-libxcam-defog.toml
id = "cl-libxcam-defog"
kind = "dev"
repo = "libxcam"
prompt = "Add an OpenCL image handler that removes atmospheric haze, following the existing dehazing (defog) handler."
rubric = "A correct solution adds an OpenCL handler following the existing cl_defog_dcp_handler pattern."
prior_art_files = ["modules/ocl/cl_defog_dcp_handler.h", "modules/ocl/cl_defog_dcp_handler.cpp"]
expected_files = ["modules/ocl/cl_defog_dcp_handler.h"]
```

- [ ] **Step 3: Create the 2 ndk tasks**

```toml
# repo_atlas/eval/tasks-closeloop/cl-ndk-audio-volume.toml
id = "cl-ndk-audio-volume"
kind = "dev"
repo = "ndk-samples"
prompt = "Add runtime volume control to the native-audio sample's playback, acquiring the OpenSL ES volume interface the same way the sample acquires its other interfaces."
rubric = "A correct solution acquires and uses the SLVolumeItf following the existing OpenSL ES interface-acquisition pattern in the native-audio sample."
prior_art_files = ["native-audio/app/src/main/cpp/native-audio-jni.cpp"]
expected_files = ["native-audio/app/src/main/cpp/native-audio-jni.cpp"]
```
```toml
# repo_atlas/eval/tasks-closeloop/cl-ndk-codec-eos.toml
id = "cl-ndk-codec-eos"
kind = "bugfix"
repo = "ndk-samples"
prompt = "Make the native-codec sample stop cleanly at end-of-stream, following the existing output-buffer and format-change handling in the decode loop."
rubric = "A correct solution handles the end-of-stream flag in the native-codec decode loop following the existing buffer/format handling."
prior_art_files = ["native-codec/app/src/main/cpp/native-codec-jni.cpp"]
expected_files = ["native-codec/app/src/main/cpp/native-codec-jni.cpp"]
```

- [ ] **Step 4: Verify all tasks load + every prior-art file exists**

Run:
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-eval-full/atlas.toml \
/home/vinc/code/knowledgeLoop/.venv/bin/python - <<'PY'
import os
from repo_atlas.eval.tasks import load_tasks
from repo_atlas.registry import load_registry
reg = {e.name: e.repo_path for e in load_registry(os.environ["REPO_ATLAS_REGISTRY"])}
tasks = load_tasks("repo_atlas/eval/tasks-closeloop")
print("tasks:", len(tasks))
missing = []
for t in tasks:
    for pf in t.prior_art_files:
        if not os.path.exists(os.path.join(reg[t.repo], pf)):
            missing.append(f"{t.id}: {pf}")
print("MISSING:", missing or "none — all prior-art files exist")
PY
```
Expected: `tasks: 11` and `MISSING: none`. Fix any missing path (grep `/mnt/x/code/corpora/<repo>`) and re-run.

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/tasks-closeloop/
git commit -m "feat(repo_atlas/eval): 11 fresh hard-prior-art close-the-loop tasks (grep-verified prior_art_files)"
```

---

## Task 6: Run the close-the-loop eval (operational, no merge)

**Files:** none. Requires local Ollama (bge-m3) + the `/home/vinc/repo-atlas-eval-full/` setup (atlas.db, atlas.toml, mcp.json).

- [ ] **Step 1: Verify prerequisites**

Run: `curl -s -m 5 http://127.0.0.1:11434/api/tags | grep -o bge-m3` (expect `bge-m3`); confirm
`/home/vinc/repo-atlas-eval-full/{atlas.db,atlas.toml,mcp.json}` exist.

- [ ] **Step 2: Run the eval in the background (~20-24 sessions, ~1.5-2.5h)**

Run (background):
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  REPO_ATLAS_JUDGE_MODEL=deepseek-chat \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas eval \
  --tasks repo_atlas/eval/tasks-closeloop --mcp-config $FULL/mcp.json \
  --out $FULL/closeloop-scorecard.md > $FULL/closeloop.log 2>&1
```
(The harness skips any task whose run/judge raises, so transient socket errors cost at most one
task, not the run.)

- [ ] **Step 3: Read the mechanism scorecard + interpret**

Read `$FULL/closeloop-scorecard.md`. Report:
- **Headline:** causal-wins / N, success baseline→treatment.
- **Difficulty self-check:** baseline success rate (target ≈30-60% — if ≥80%, tasks were too easy,
  note it).
- **Category histogram:** causal-win / surfaced-ignored / retrieval-miss / win-unattributed /
  regression / no-effect — and what each implies (retrieval works & helps / adoption gap /
  retrieval gap / variance / hurt / no headroom).
- Adoption rate (should be ≈100%), exploration delta.

- [ ] **Step 4: Report (no merge — leave for the human)**

Summarize the causal verdict. STOP before any `git merge`/`git push`.

---

## Self-review checklist (done while writing)

- **Spec coverage:** Task.prior_art_files (T1), mechanism capture in runner (T2), causal classifier (T3), threading + Mechanism report (T4), 11 fresh grep-verified hard-prior-art tasks (T5), run + interpret (T6). Non-goals (third arm, new judge, cross-repo) excluded.
- **Type/field consistency:** `RunResult.{find_related_queries, retrieval_surfaced_gold}`, `TaskScore.{retrieval_surfaced_gold, reused_prior_art}`, `PairResult.category`, `classify(b,t,surfaced,reused,adopted)` keyword args, and the `summary` keys (`causal_wins`, `categories`, `surfaced_rate`, `reused_rate`) are used identically across runner emit (T2), classifier (T3), aggregate/harness/report (T4), and the tests.
- **Additive, back-compatible:** every new dataclass field has a default, so existing TaskScore/RunResult/PairResult constructions and tests keep working; T4 Step 6 runs the existing eval tests and updates only genuinely-broken assertions.
- **No placeholders:** every prior-art path is concrete + grep-verified; every code/command step is complete with expected output.
