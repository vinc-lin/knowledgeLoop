# Grounding-Based Finding-Bottleneck Eval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unverifiable LLM judge with a mechanically-checkable `GroundingScorer` (success = the agent's diff references the required real API), add 11 grep-verified finding-bottleneck tasks, and run baseline-vs-treatment to reliably measure whether repo_atlas makes the agent ground in the right existing API.

**Architecture:** Per `docs/superpowers/specs/2026-06-21-grounded-finding-bottleneck-eval-design.md`. Reuses `repo_atlas/eval/` (`ClaudeRunner`, harness, aggregate, report, the close-the-loop mechanism trace) + `Task.prior_art_files`. Adds `Task.required_apis`, a `GroundingScorer`, a `--scorer grounding` CLI flag, and the task set.

**Tech Stack:** Python 3.12, pytest. Run env identical to the close-the-loop run (local Ollama bge-m3 for treatment's find_related; **no judge model** — grounding is local).

**Conventions:**
- Run tests: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest <file> -m "not integration" -p no:cacheprovider --no-cov -q`
- `tests/` is gitignored → `git add -f`. `from __future__ import annotations`; line length 100.

---

## Task 1: `Task.required_apis`

**Files:**
- Modify: `repo_atlas/eval/tasks.py`
- Test: `tests/test_eval_required_apis.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_required_apis.py
from repo_atlas.eval.tasks import Task, load_tasks


def test_required_apis_default():
    assert Task(id="t", kind="dev", repo="r", prompt="p", rubric="x").required_apis == []


def test_load_reads_required_apis(tmp_path):
    (tmp_path / "a.toml").write_text(
        'id="t1"\nkind="dev"\nrepo="r"\nprompt="p"\nrubric="x"\n'
        'required_apis=["cgeFooBar"]\nprior_art_files=["src/a.cpp"]\n')
    t = load_tasks(str(tmp_path))[0]
    assert t.required_apis == ["cgeFooBar"] and t.prior_art_files == ["src/a.cpp"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_required_apis.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `TypeError`/`AttributeError` (no `required_apis`).

- [ ] **Step 3: Implement in `repo_atlas/eval/tasks.py`**

Add the field (after `prior_art_files`):
```python
    required_apis: list = field(default_factory=list)
```
In `load_tasks`, add to the `Task(...)` kwargs:
```python
            required_apis=list(d.get("required_apis", [])),
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_required_apis.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
git add repo_atlas/eval/tasks.py
git add -f tests/test_eval_required_apis.py
git commit -m "feat(repo_atlas/eval): Task.required_apis (grounding gold)"
```

---

## Task 2: `GroundingScorer` (judge replacement)

**Files:**
- Create: `repo_atlas/eval/grounding_scorer.py`
- Test: `tests/test_eval_grounding_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_grounding_scorer.py
import pytest
from repo_atlas.eval.grounding_scorer import GroundingScorer
from repo_atlas.eval.runner import RunResult
from repo_atlas.eval.tasks import Task


def _task(apis):
    return Task(id="t", kind="dev", repo="r", prompt="p", rubric="x", required_apis=apis)


@pytest.mark.asyncio
async def test_grounded_success_when_all_apis_referenced():
    run = RunResult("treatment", referenced_symbols=["cgeFoo", "x", "y"])
    assert await GroundingScorer().score(_task(["cgeFoo"]), run) is True


@pytest.mark.asyncio
async def test_not_grounded_when_api_missing():
    run = RunResult("treatment", referenced_symbols=["x", "y"])
    assert await GroundingScorer().score(_task(["cgeFoo"]), run) is False


@pytest.mark.asyncio
async def test_all_required_semantics():
    run = RunResult("treatment", referenced_symbols=["a"])
    assert await GroundingScorer().score(_task(["a", "b"]), run) is False   # needs both


@pytest.mark.asyncio
async def test_empty_required_is_false():
    run = RunResult("treatment", referenced_symbols=["a"])
    assert await GroundingScorer().score(_task([]), run) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_grounding_scorer.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `repo_atlas/eval/grounding_scorer.py`**

```python
from __future__ import annotations


class GroundingScorer:
    """Judge replacement: success = the agent's diff references EVERY required real API.

    Existence of the APIs is guaranteed at curation time (the gold-api verifier greps source),
    so the scorer only needs to confirm the agent USED them — no compiler, no LLM judge. The
    `.score(task, run)` signature matches GatewayJudge so it is a drop-in in harness._score.
    Matching is on the bare callable token the agent writes (e.g. `cgeFoo` from `cgeFoo(...)`),
    which is exactly what ClaudeRunner's extract_refs produces into run.referenced_symbols."""

    async def score(self, task, run) -> bool:
        if not task.required_apis:
            return False
        referenced = set(run.referenced_symbols)
        return all(api in referenced for api in task.required_apis)
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_grounding_scorer.py -p no:cacheprovider --no-cov -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/grounding_scorer.py
git add -f tests/test_eval_grounding_scorer.py
git commit -m "feat(repo_atlas/eval): GroundingScorer — success = diff references the required real API (no judge)"
```

---

## Task 3: Wire grounding into the eval (CLI flag + mechanism credit)

**Files:**
- Modify: `repo_atlas/cli.py` (`--scorer` flag + branch)
- Modify: `repo_atlas/eval/harness.py` (`_score` credits referenced required_apis as `reused_prior_art`)
- Test: `tests/test_eval_harness.py` (add a grounding-reuse case)

- [ ] **Step 1: Add the failing test (to `tests/test_eval_harness.py`)**

```python
@pytest.mark.asyncio
async def test_score_credits_required_api_reference_as_reused():
    from repo_atlas.eval.harness import _score
    from repo_atlas.eval.tasks import Task
    from repo_atlas.eval.runner import RunResult
    from repo_atlas.eval.grounding_scorer import GroundingScorer
    task = Task(id="t", kind="dev", repo="r", prompt="p", rubric="x", required_apis=["cgeFoo"])
    run = RunResult("treatment", referenced_symbols=["cgeFoo"], touched_files=[])
    score = await _score(task, run, judge=GroundingScorer(), exists_fn=lambda s: True)
    assert score.success is True            # grounded
    assert score.reused_prior_art is True   # referencing the required api counts as reuse/grounded
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_harness.py::test_score_credits_required_api_reference_as_reused -p no:cacheprovider --no-cov -q`
Expected: FAIL — `reused_prior_art` is `False` (current `_score` only checks `prior_art_files` ∈ `touched_files`).

- [ ] **Step 3: Implement in `repo_atlas/eval/harness.py`**

In `_score`, change the `reused_prior_art=...` argument of the `TaskScore(...)` call to also credit a
referenced required API:
```python
        reused_prior_art=(any(pf in run.touched_files for pf in task.prior_art_files)
                          or any(api in run.referenced_symbols for api in task.required_apis)))
```

- [ ] **Step 4: Add the `--scorer` flag in `repo_atlas/cli.py`**

In `build_parser`, on the `eval` subparser (`ev`), add:
```python
    ev.add_argument("--scorer", choices=["judge", "grounding"], default="judge",
                    help="grounding = mechanically check the diff references required_apis (no judge)")
```
In `_run_eval`, replace the `judge = GatewayJudge(...)` construction with:
```python
    if args.scorer == "grounding":
        from repo_atlas.eval.grounding_scorer import GroundingScorer
        judge = GroundingScorer()
    else:
        judge = GatewayJudge(cfg.base_url, cfg.api_key,
                             os.environ.get("REPO_ATLAS_JUDGE_MODEL", "deepseek-chat"))
```

- [ ] **Step 5: Run to verify it passes (+ no regressions)**

Run:
```bash
/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_eval_harness.py tests/test_eval_aggregate.py \
  -m "not integration" -p no:cacheprovider --no-cov -q
```
Expected: PASS (existing harness/aggregate tests + the new case).

- [ ] **Step 6: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/cli.py repo_atlas/eval/harness.py
git add repo_atlas/cli.py repo_atlas/eval/harness.py
git add -f tests/test_eval_harness.py
git commit -m "feat(repo_atlas/eval): --scorer grounding + credit required-api reference as grounded in the mechanism trace"
```

---

## Task 4: The 11 finding-bottleneck tasks + gold-api verifier

**Files:**
- Create: `repo_atlas/eval/tasks-grounding/*.toml` (11 tasks)
- Create: `scripts/verify_grounding_tasks.py`

Every `required_apis` symbol is grep-verified to exist in its `prior_art_files`. `prior_art_files`
holds the defining file (drives the `surfaced` mechanism signal); `required_apis` holds the bare
callable token (drives grounded-success). Rubric is informational (the grounding scorer, not a
judge, decides success).

- [ ] **Step 1: Create the 5 gpuimage tasks**

```toml
# repo_atlas/eval/tasks-grounding/gb-gpuimage-scale-buffer.toml
id = "gb-gpuimage-scale-buffer"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Before uploading a decoded RGBA image to an OpenGL texture in the CGE image handler, large source images must be downscaled so they fit within the GPU's maximum texture dimensions. Add a step that, given the raw pixel buffer plus its width/height and channel count, produces a newly-allocated downscaled copy (updating width/height in place) when the image exceeds the max texture size, and leaves it untouched otherwise."
rubric = "Correct iff the solution calls the existing cgeGetScaledBufferInSize helper rather than reinventing a resampling loop or fabricating a name."
required_apis = ["cgeGetScaledBufferInSize"]
prior_art_files = ["library/src/main/jni/cge/common/cgeGLFunctions.cpp"]
expected_files = ["library/src/main/jni/cge/common/cgeGLFunctions.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-gpuimage-blend-mode-name.toml
id = "gb-gpuimage-blend-mode-name"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Given a CGETextureBlendMode enum value (e.g. CGE_BLEND_OVERLAY, CGE_BLEND_SOFTLIGHT), return the canonical lowercase string name of that blend mode ('overlay', 'softlight', ...) for logging/serialization, with an option to return the localized name. Return null for an out-of-range mode."
rubric = "Correct iff the solution calls the existing cgeGetBlendModeName rather than hand-rolling a switch/table or fabricating a name."
required_apis = ["cgeGetBlendModeName"]
prior_art_files = ["library/src/main/jni/cge/common/cgeCommonDefine.cpp"]
expected_files = ["library/src/main/jni/cge/common/cgeCommonDefine.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-gpuimage-gen-texture.toml
id = "gb-gpuimage-gen-texture"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Implement a helper that creates a new OpenGL 2D texture from a raw CPU pixel buffer: activate the right texture unit, generate and bind the texture, pick the correct sized/internal format from the channel count, upload the pixels (or allocate empty storage when the buffer is null), set min/mag filtering and S/T wrap modes, and return the new texture id. It must transparently use glTexStorage2D on Android NDK builds when allocating empty 8-bit storage."
rubric = "Correct iff the solution calls the existing cgeGenTextureWithBuffer factory rather than inlining glGenTextures boilerplate or fabricating a name."
required_apis = ["cgeGenTextureWithBuffer"]
prior_art_files = ["library/src/main/jni/cge/common/cgeCommonDefine.cpp"]
expected_files = ["library/src/main/jni/cge/common/cgeCommonDefine.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-gpuimage-format-decode.toml
id = "gb-gpuimage-format-decode"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "Given a CGEBufferFormat enum (e.g. CGE_FORMAT_RGBA_INT8, CGE_FORMAT_RGB_FLOAT32), resolve the corresponding OpenGL data type (GL_UNSIGNED_BYTE / GL_UNSIGNED_SHORT / GL_FLOAT), the channel/pixel format (GL_RGB / GL_RGBA / ...), and the channel count, writing them out so callers can use them for glReadPixels / glTexImage2D and buffer-size math."
rubric = "Correct iff the solution calls the existing cgeGetDataAndChannelByFormat decoder rather than hand-rolling a switch or fabricating a name."
required_apis = ["cgeGetDataAndChannelByFormat"]
prior_art_files = ["library/src/main/jni/cge/common/cgeCommonDefine.cpp"]
expected_files = ["library/src/main/jni/cge/common/cgeCommonDefine.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-gpuimage-readback.toml
id = "gb-gpuimage-readback"
kind = "dev"
repo = "android-gpuimage-plus"
prompt = "After running filters through a CGEImageHandler, copy the processed image out of the GPU framebuffer back into a caller-provided CPU buffer in a requested pixel format (e.g. RGBA 8-bit), handling the framebuffer bind, glFinish, pack-alignment and (on ES 3.0) the PBO read path. Return whether the readback succeeded."
rubric = "Correct iff the solution calls the existing CGEImageHandler::getOutputBufferData rather than writing its own glReadPixels or fabricating a name."
required_apis = ["getOutputBufferData"]
prior_art_files = ["library/src/main/jni/cge/common/cgeImageHandler.cpp"]
expected_files = ["library/src/main/jni/cge/common/cgeImageHandler.cpp"]
```

- [ ] **Step 2: Create the 3 libxcam tasks**

```toml
# repo_atlas/eval/tasks-grounding/gb-libxcam-planar-info.toml
id = "gb-libxcam-planar-info"
kind = "dev"
repo = "libxcam"
prompt = "Inside a handler I have a VideoBuffer for an NV12 frame and need to walk its luma (Y) plane and then its chroma (UV) plane to copy/process pixels. For each plane I need its width, height, byte offset into the buffer, and pitch (stride). Get those per-plane geometry values for plane index 0 and plane index 1 from the buffer's VideoBufferInfo."
rubric = "Correct iff the solution calls VideoBufferInfo::get_planar_info rather than reading strides/offsets by hand or fabricating a name."
required_apis = ["get_planar_info"]
prior_art_files = ["xcore/video_buffer.cpp"]
expected_files = ["xcore/video_buffer.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-libxcam-convert-clbuffer.toml
id = "gb-libxcam-convert-clbuffer"
kind = "dev"
repo = "libxcam"
prompt = "I'm writing an OpenCL image handler. The execute path hands me a generic SmartPtr<VideoBuffer> for the input frame, but to bind it as a kernel argument I need it as a SmartPtr<CLBuffer> so the underlying cl_mem is accessible. Turn the incoming VideoBuffer into the CLBuffer that backs it."
rubric = "Correct iff the solution calls the existing convert_to_clbuffer helper rather than dynamic_cast-ing or rebuilding a cl_mem by hand."
required_apis = ["convert_to_clbuffer"]
prior_art_files = ["modules/ocl/cl_utils.cpp"]
expected_files = ["modules/ocl/cl_utils.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-libxcam-fps-macro.toml
id = "gb-libxcam-fps-macro"
kind = "dev"
repo = "libxcam"
prompt = "In the GStreamer src/filter element's per-frame output path I want a lightweight built-in way to print the current and running-average frames-per-second every N frames to stdout for debugging, without adding my own timing state. Emit an FPS log line tagged with this element's name once every 30 frames."
rubric = "Correct iff the solution uses the existing XCAM_STATIC_FPS_CALCULATION macro rather than rolling its own gettimeofday-based counter."
required_apis = ["XCAM_STATIC_FPS_CALCULATION"]
prior_art_files = ["xcore/xcam_obj_debug.h"]
expected_files = ["xcore/xcam_obj_debug.h"]
```

- [ ] **Step 3: Create the 3 ndk-samples tasks**

```toml
# repo_atlas/eval/tasks-grounding/gb-ndk-sensormanager.toml
id = "gb-ndk-sensormanager"
kind = "dev"
repo = "ndk-samples"
prompt = "In the accelerometer sensor-graph native sample (sensor-graph/accelerometer/src/main/cpp/sensorgraph.cpp), the code obtains an ASensorManager to read the accelerometer. Implement/restore the helper that returns a valid ASensorManager* instance in a way that works across Android API levels: it must prefer the package-scoped instance accessor when present and fall back gracefully otherwise, instead of calling the plain deprecated global accessor directly. Wire the sensor init path to use it."
rubric = "Correct iff the solution calls AcquireASensorManagerInstance rather than ASensorManager_getInstance() directly."
required_apis = ["AcquireASensorManagerInstance"]
prior_art_files = ["sensor-graph/accelerometer/src/main/cpp/sensorgraph.cpp"]
expected_files = ["sensor-graph/accelerometer/src/main/cpp/sensorgraph.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-ndk-metadata-tag.toml
id = "gb-ndk-metadata-tag"
kind = "dev"
repo = "ndk-samples"
prompt = "In the camera-utils module (camera/camera-utils), when logging or debugging ACameraMetadata entries you have a raw acamera_metadata_tag_t value (e.g. ACAMERA_LENS_FACING) and need a human-readable name for it to put in a log line. Add a log statement that prints the tag's readable name alongside its hex value, using the module's existing facility for converting a metadata tag enum to its string name."
rubric = "Correct iff the solution calls the existing GetTagStr rather than hand-writing a switch or fabricating an NDK call."
required_apis = ["GetTagStr"]
prior_art_files = ["camera/camera-utils/src/main/cpp/camera_utils.cpp"]
expected_files = ["camera/camera-utils/src/main/cpp/camera_utils.cpp"]
```
```toml
# repo_atlas/eval/tasks-grounding/gb-ndk-arraysize.toml
id = "gb-ndk-arraysize"
kind = "dev"
repo = "ndk-samples"
prompt = "You are adding a new JNI entry point to one of the NDK samples. In JNI_OnLoad you build a static JNINativeMethod methods[] array and call env->RegisterNatives(clazz, methods, <count>). Supply the <count> argument using the element-count utility this repo already standardizes on for exactly this purpose, rather than computing it by hand."
rubric = "Correct iff the solution uses the existing arraysize() macro rather than sizeof(a)/sizeof(a[0])."
required_apis = ["arraysize"]
prior_art_files = ["base/src/main/cpp/include/base/macros.h"]
expected_files = ["base/src/main/cpp/include/base/macros.h"]
```

- [ ] **Step 4: Write the gold-api verifier**

```python
# scripts/verify_grounding_tasks.py
"""Assert every required_apis symbol exists in its task's prior_art_files (grep). Usage:
  REPO_ATLAS_REGISTRY=/path/atlas.toml python scripts/verify_grounding_tasks.py [CASES_DIR]
"""
import os
import sys

from repo_atlas.eval.tasks import load_tasks
from repo_atlas.registry import load_registry


def main() -> int:
    cases = sys.argv[1] if len(sys.argv) > 1 else "repo_atlas/eval/tasks-grounding"
    reg = {e.name: e.repo_path
           for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    bad = []
    tasks = load_tasks(cases)
    for t in tasks:
        base = reg.get(t.repo)
        if not base:
            bad.append(f"{t.id}: repo {t.repo!r} not in registry")
            continue
        if not t.required_apis:
            bad.append(f"{t.id}: no required_apis")
        for api in t.required_apis:
            bare = api.split("::")[-1]
            found = any(os.path.exists(os.path.join(base, pf))
                        and bare in open(os.path.join(base, pf), errors="ignore").read()
                        for pf in t.prior_art_files)
            if not found:
                bad.append(f"{t.id}: {api} not found in prior_art_files")
    if bad:
        print("PROBLEMS:")
        for b in bad:
            print("  -", b)
        return 1
    print(f"OK: {len(tasks)} tasks, all required_apis exist in their prior-art files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Verify the task set**

Run:
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-eval-full/atlas.toml \
  /home/vinc/code/knowledgeLoop/.venv/bin/python scripts/verify_grounding_tasks.py
```
Expected: `OK: 11 tasks, all required_apis exist in their prior-art files`. Fix any problem and re-run.

- [ ] **Step 6: Commit**

```bash
git add repo_atlas/eval/tasks-grounding/ scripts/verify_grounding_tasks.py
git commit -m "feat(repo_atlas/eval): 11 finding-bottleneck grounding tasks (grep-verified non-obvious required_apis) + verifier"
```

---

## Task 5: Run the grounding eval + interpret (operational, no merge)

**Files:** none. Requires local Ollama (bge-m3) + the `/home/vinc/repo-atlas-eval-full/` setup.

- [ ] **Step 1: Verify prereqs**

Run: `curl -s -m 5 http://127.0.0.1:11434/api/tags | grep -o bge-m3` (expect `bge-m3`); confirm
`/home/vinc/repo-atlas-eval-full/{atlas.db,atlas.toml,mcp.json}` exist.

- [ ] **Step 2: Run the grounding eval in the background (~22 sessions, ~1.5-2.5h)**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas eval \
  --tasks repo_atlas/eval/tasks-grounding --scorer grounding --mcp-config $FULL/mcp.json \
  --out $FULL/grounding-scorecard.md > $FULL/grounding.log 2>&1
```
(No judge model is used. The harness skips any task whose run raises, so a socket error costs at
most one task.)

- [ ] **Step 3: Read the scorecard + interpret**

Read `$FULL/grounding-scorecard.md`. Report:
- **Primary — grounded-success:** baseline → treatment (and the delta). This is "did the agent use
  the required real API."
- **Baseline-miss honesty check:** baseline grounded-success should be **LOW** — that is the whole
  premise (finding the non-obvious API is the bottleneck). If baseline grounded-success is already
  high (≥~70%), the tasks were not finding-bottleneck — say so; the result is then uninformative.
- **Mechanism:** `surfaced` (find_related returned the API's defining file) and the causal
  histogram (causal-win = treatment grounded where baseline didn't + surfaced).
- Adoption (≈100% expected), exploration.

- [ ] **Step 4: Report (no merge — leave for the human)**

State the verdict in the spec's narrow terms ("repo_atlas makes the agent ground in the right real
API more / less" — not full correctness). STOP before any `git merge`/`git push`.

---

## Self-review checklist (done while writing)

- **Spec coverage:** Task.required_apis (T1), GroundingScorer (T2), `--scorer grounding` flag +
  mechanism credit (T3), 11 grep-verified finding-bottleneck tasks + verifier (T4), run + interpret
  with the baseline-miss honesty check (T5). Non-goals (executable verification, consume change,
  full-correctness claim) excluded.
- **Reference matching:** every `required_apis` entry is a bare callable token (e.g. `get_planar_info`,
  `arraysize`) that `extract_refs` catches at a call site; the `VideoBufferInfo::init` candidate was
  dropped because its diff token (`init`) is too generic.
- **Existence handled correctly:** the scorer does NOT use `store.symbols_exist` (it misses macros
  like `arraysize`/`XCAM_STATIC_FPS_CALCULATION`); existence is guaranteed by the source-grep
  verifier (T4) at curation time, per the spec's "verified to exist."
- **Additive/back-compatible:** `required_apis` has a default; `_score`'s reuse change is an added OR
  clause; `--scorer` defaults to `judge` so the existing agentic eval is unchanged. No placeholders —
  all 11 prompts + paths are concrete and grep-verified.
```
