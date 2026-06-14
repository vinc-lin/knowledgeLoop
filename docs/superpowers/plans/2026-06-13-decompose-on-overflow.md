# Reactive Decompose-on-Overflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make oversized modules succeed on small-output models by reactively falling back from single-doc to decomposition when a doc write overflows the model's output cap.

**Architecture:** Add a `decompose_on_overflow` boolean to `ModelProfile` (default true, overridable). In `PydanticAIBackend.run_module_agent`, catch the `IncompleteToolCall` raised when a single-doc write overflows the cap and — when no doc was written and the flag is on and we started as a leaf agent — rebuild as the complex (decomposing) agent and retry once. The existing `is_complex_module` proactive trigger is unchanged; the orchestrator is untouched. Then use the feature to close the three known `codebase-memory-mcp` gaps and reconcile the wiki.

**Tech Stack:** Python 3.12, pydantic-ai, pytest / pytest-asyncio, tree-sitter (parsing, unaffected here).

---

## Reference: current code being changed

`codewiki/src/be/pydantic_ai_backend.py` `run_module_agent` (lines ~56–145) currently:
- early-returns if `overview.md` exists, then if `{module_name}.md` exists (lines 69–76);
- branches on `is_complex_module(...)` to build a complex or leaf `Agent` (lines 78–97);
- builds `CodeWikiDeps` (99–111);
- runs the agent in a `try`; the `except` treats "raised after the doc already exists" as complete, else `raise` (113–144).

`codewiki/src/be/model_profiles.py`: `ModelProfile` is a `@dataclass(frozen=True)` with 10 fields and no defaults; `_merge` rebuilds via `ModelProfile(**fields)`; `resolve_profile(provider, model, user_override=None)` layers base → registry → override. `Config.__post_init__` resolves and retains `self.profile`.

`tests/` is gitignored; new test files must be added with `git add -f`. `pyproject.toml` sets `--cov`, so run pytest with `pytest-cov` installed or append `--no-cov`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `codewiki/src/be/model_profiles.py` | Per-model operational profile | Add `decompose_on_overflow: bool = True` field |
| `codewiki/src/be/pydantic_ai_backend.py` | API-path agent runner | Add `IncompleteToolCall` import; add `_tools_for`, `_build_agent`, `_should_escalate`; reactive retry loop in `run_module_agent` |
| `tests/test_decompose_on_overflow.py` | Tests for the feature | New file (`git add -f`) |
| `docs/findings-and-practices.md` | Operational lessons | One short note on the new option |
| target repo `codebase-memory-mcp/codewiki-docs/` | The wiki output | Regenerated gap docs + tree + index.html + metadata (Task 5) |

---

## Task 1: Add `decompose_on_overflow` to ModelProfile

**Files:**
- Modify: `codewiki/src/be/model_profiles.py` (the `ModelProfile` dataclass, ~lines 52–64)
- Test: `tests/test_decompose_on_overflow.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_decompose_on_overflow.py`:

```python
"""Reactive decompose-on-overflow: profile flag, escalation decision, agent wiring."""

import os
import json

import pytest

from codewiki.src.be.model_profiles import resolve_profile


# --- Task 1: ModelProfile.decompose_on_overflow ---------------------------

def test_decompose_on_overflow_default_true():
    p = resolve_profile("openai-compatible", "deepseek-chat")
    assert p.decompose_on_overflow is True


def test_decompose_on_overflow_user_override_false():
    p = resolve_profile("openai-compatible", "deepseek-chat",
                        {"decompose_on_overflow": False})
    assert p.decompose_on_overflow is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: 'ModelProfile' object has no attribute 'decompose_on_overflow'`.

- [ ] **Step 3: Add the field**

In `codewiki/src/be/model_profiles.py`, add the field as the **last** field of `ModelProfile` (after `honored`), with a default so existing positional/kwarg constructors keep working:

```python
    honored: frozenset                   # API_HONORED or CAW_HONORED
    decompose_on_overflow: bool = True   # leaf write overflow -> retry as decompose
```

(No change needed to `_merge`: it iterates `dataclasses.fields(ModelProfile)`, so the new key is carried; the override loop applies `False` because `False is not None`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Verify no regression in existing profile tests**

Run: `.venv/bin/python -m pytest tests/test_model_profiles.py -p no:cacheprovider --no-cov -q`
Expected: PASS (existing positional `ModelProfile(...)` constructions still work because the new field has a default).

- [ ] **Step 6: Commit**

```bash
git add -f codewiki/src/be/model_profiles.py tests/test_decompose_on_overflow.py
git commit -m "feat(profiles): add decompose_on_overflow flag (default true)"
```

---

## Task 2: Extract `_tools_for` and `_build_agent` (no behavior change)

**Files:**
- Modify: `codewiki/src/be/pydantic_ai_backend.py` (agent construction, lines ~78–97)
- Test: `tests/test_decompose_on_overflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decompose_on_overflow.py`:

```python
from codewiki.src.be.pydantic_ai_backend import PydanticAIBackend
from codewiki.src.be.agent_tools.generate_sub_module_documentations import (
    generate_sub_module_documentation_tool,
)


def test_tools_for_leaf_excludes_submodule_tool():
    tools = PydanticAIBackend._tools_for(False)
    assert generate_sub_module_documentation_tool not in tools


def test_tools_for_complex_includes_submodule_tool():
    tools = PydanticAIBackend._tools_for(True)
    assert generate_sub_module_documentation_tool in tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -k tools_for -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: type object 'PydanticAIBackend' has no attribute '_tools_for'`.

- [ ] **Step 3: Add the helpers and use them at the construction site**

In `codewiki/src/be/pydantic_ai_backend.py`, add these methods to `PydanticAIBackend` (e.g. just above `run_module_agent`):

```python
    @staticmethod
    def _tools_for(complex_: bool) -> list:
        """Toolset for a module agent. Complex modules also get the decomposition tool."""
        base = [read_code_components_tool, str_replace_editor_tool]
        if complex_:
            return base + [generate_sub_module_documentation_tool]
        return base

    def _build_agent(self, module_name: str, *, complex_: bool) -> Agent:
        """Build the leaf or complex documentation agent for a module."""
        system_prompt = (
            format_system_prompt(module_name, self._custom_instructions)
            if complex_
            else format_leaf_system_prompt(module_name, self._custom_instructions)
        )
        return Agent(
            self._fallback_models,
            name=module_name,
            deps_type=CodeWikiDeps,
            tools=self._tools_for(complex_),
            system_prompt=system_prompt,
        )
```

Then replace the existing `if is_complex_module(...): agent = Agent(...) else: agent = Agent(...)` block (lines ~78–97) with:

```python
        complex_ = is_complex_module(components, core_component_ids)
        agent = self._build_agent(module_name, complex_=complex_)
```

(Leave the rest — deps construction and the `try/except` — unchanged for now; Task 4 wraps them.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -k tools_for -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add codewiki/src/be/pydantic_ai_backend.py
git add -f tests/test_decompose_on_overflow.py
git commit -m "refactor(backend): extract _tools_for/_build_agent (no behavior change)"
```

---

## Task 3: Add the `_should_escalate` decision helper

**Files:**
- Modify: `codewiki/src/be/pydantic_ai_backend.py` (add import + static method)
- Test: `tests/test_decompose_on_overflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decompose_on_overflow.py`:

```python
from pydantic_ai.exceptions import IncompleteToolCall


def _overflow():
    return IncompleteToolCall("output limit exceeded")


def test_should_escalate_true_on_leaf_overflow_no_doc_flag_on():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=True,
        already_complex=False, escalated=False) is True


def test_should_escalate_false_when_flag_off():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=False,
        already_complex=False, escalated=False) is False


def test_should_escalate_false_when_already_complex():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=True,
        already_complex=True, escalated=False) is False


def test_should_escalate_false_when_already_escalated():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=True,
        already_complex=False, escalated=True) is False


def test_should_escalate_false_when_doc_written():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=True, decompose_on_overflow=True,
        already_complex=False, escalated=False) is False


def test_should_escalate_false_on_other_exception():
    assert PydanticAIBackend._should_escalate(
        ValueError("nope"), doc_exists=False, decompose_on_overflow=True,
        already_complex=False, escalated=False) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -k should_escalate -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: ... '_should_escalate'`.

- [ ] **Step 3: Add the import and the helper**

In `codewiki/src/be/pydantic_ai_backend.py`, add the import near the other pydantic-ai import (after line 16 `from pydantic_ai import Agent`):

```python
from pydantic_ai.exceptions import IncompleteToolCall
```

Add the static method to `PydanticAIBackend` (next to `_tools_for`):

```python
    @staticmethod
    def _should_escalate(exc: BaseException, *, doc_exists: bool,
                         decompose_on_overflow: bool, already_complex: bool,
                         escalated: bool) -> bool:
        """A leaf agent overflowed the output cap mid-write and we may retry as decompose."""
        return (
            isinstance(exc, IncompleteToolCall)
            and not doc_exists
            and decompose_on_overflow
            and not already_complex
            and not escalated
        )
```

Note: the tests call it with keyword args (`doc_exists=...`); keep these keyword-only via the `*`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -k should_escalate -p no:cacheprovider --no-cov -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add codewiki/src/be/pydantic_ai_backend.py
git add -f tests/test_decompose_on_overflow.py
git commit -m "feat(backend): add _should_escalate overflow-retry decision helper"
```

---

## Task 4: Wire the reactive retry loop into `run_module_agent`

**Files:**
- Modify: `codewiki/src/be/pydantic_ai_backend.py` (`run_module_agent` body, lines ~78–144)
- Test: `tests/test_decompose_on_overflow.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_decompose_on_overflow.py`:

```python
import codewiki.src.be.pydantic_ai_backend as pab
from codewiki.src.config import Config, MODULE_TREE_FILENAME


class _FakeAgent:
    """Stand-in for pydantic-ai Agent: leaf run overflows; complex run writes the doc."""

    def __init__(self, model, name=None, deps_type=None, tools=None, system_prompt=None):
        self.tools = tools or []
        self.name = name

    async def run(self, prompt, deps=None, usage_limits=None):
        is_complex = generate_sub_module_documentation_tool in self.tools
        if not is_complex:
            raise IncompleteToolCall("output limit exceeded")
        with open(os.path.join(deps.absolute_docs_path,
                               f"{deps.current_module_name}.md"), "w", encoding="utf-8") as fh:
            fh.write("# decomposed doc\n")


def _backend(tmp_path, monkeypatch, *, decompose):
    monkeypatch.setattr(pab, "Agent", _FakeAgent)
    monkeypatch.setattr(pab, "create_fallback_models", lambda cfg: object())
    monkeypatch.setattr(pab, "build_usage_limits", lambda cfg: None)
    from codewiki.src.be.model_profiles import resolve_profile
    prof = resolve_profile("openai-compatible", "deepseek-chat",
                           {"decompose_on_overflow": decompose})
    cfg = Config(
        repo_path=str(tmp_path), output_dir=str(tmp_path), dependency_graph_dir=str(tmp_path),
        docs_dir=str(tmp_path), max_depth=3, llm_base_url="http://gw/v1", llm_api_key="k",
        main_model="deepseek-chat", cluster_model="deepseek-chat", fallback_model="fb",
        provider="openai-compatible", profile=prof,
    )
    # minimal module tree so format_user_prompt + the loader have data
    with open(os.path.join(str(tmp_path), MODULE_TREE_FILENAME), "w", encoding="utf-8") as fh:
        json.dump({"Mod": {"components": [], "children": {}}}, fh)
    return pab.PydanticAIBackend(cfg)


@pytest.mark.asyncio
async def test_run_module_agent_escalates_on_overflow(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch, decompose=True)
    await backend.run_module_agent(
        module_name="Mod", components={}, core_component_ids=[],
        module_path=["Mod"], working_dir=str(tmp_path))
    assert os.path.exists(os.path.join(str(tmp_path), "Mod.md"))


@pytest.mark.asyncio
async def test_run_module_agent_reraises_when_flag_off(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch, decompose=False)
    with pytest.raises(IncompleteToolCall):
        await backend.run_module_agent(
            module_name="Mod", components={}, core_component_ids=[],
            module_path=["Mod"], working_dir=str(tmp_path))
    assert not os.path.exists(os.path.join(str(tmp_path), "Mod.md"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -k run_module_agent -p no:cacheprovider --no-cov -q`
Expected: FAIL — `test_..._escalates_on_overflow` raises `IncompleteToolCall` (no retry yet); no `Mod.md` written.

- [ ] **Step 3: Replace the run/except body with the retry loop**

In `run_module_agent`, after the early-return guards (the `overview.md` / `{module_name}.md` existence checks) and after `complex_ = is_complex_module(...)` from Task 2, replace the single agent build + deps + `try/except` (current lines ~78–144) with this loop:

```python
        complex_ = is_complex_module(components, core_component_ids)
        escalated = False
        while True:
            agent = self._build_agent(module_name, complex_=complex_)
            deps = CodeWikiDeps(
                absolute_docs_path=working_dir,
                absolute_repo_path=str(os.path.abspath(config.repo_path)),
                registry={},
                components=components,
                path_to_current_module=module_path,
                current_module_name=module_name,
                module_tree=module_tree,
                max_depth=config.max_depth,
                current_depth=1,
                config=config,
                custom_instructions=self._custom_instructions,
            )
            try:
                await agent.run(
                    format_user_prompt(
                        module_name=module_name,
                        core_component_ids=core_component_ids,
                        components=components,
                        module_tree=deps.module_tree,
                    ),
                    deps=deps,
                    usage_limits=build_usage_limits(config),
                )
                logger.info("module %s diagnostics: %s", module_name, deps.diagnostics.summary())
                file_manager.save_json(deps.module_tree, module_tree_path)
                return deps.module_tree
            except Exception as e:
                logger.info("module %s diagnostics (on raise): %s",
                            module_name, deps.diagnostics.summary())
                docs_path = os.path.join(working_dir, f"{module_name}.md")
                if os.path.exists(docs_path):
                    # Doc already written; an extra oversized tool call raised. Done.
                    logger.warning(
                        "Module %s agent raised after writing docs (%s); treating as complete",
                        module_name, e,
                    )
                    file_manager.save_json(deps.module_tree, module_tree_path)
                    return deps.module_tree
                if self._should_escalate(
                    e, doc_exists=False,
                    decompose_on_overflow=config.profile.decompose_on_overflow,
                    already_complex=complex_, escalated=escalated,
                ):
                    logger.warning(
                        "Module %s overflowed the output cap as a single doc; "
                        "escalating to decompose mode", module_name,
                    )
                    complex_ = True
                    escalated = True
                    module_tree = file_manager.load_json(module_tree_path)  # clean retry state
                    continue
                logger.error("Error processing module %s: %s", module_name, e)
                logger.error("Traceback: %s", traceback.format_exc())
                raise
```

Notes for the implementer:
- `module_tree` was already loaded near the top of `run_module_agent` (`module_tree = file_manager.load_json(module_tree_path)`); the loop reuses and (on escalation) reloads it.
- `config = self._config` is set near the top; `config.profile.decompose_on_overflow` reads the resolved profile flag.
- `deps` is now built **inside** the loop so each attempt gets fresh `module_tree`/diagnostics.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_decompose_on_overflow.py -p no:cacheprovider --no-cov -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -q`
Expected: PASS (all existing tests + the new file).

- [ ] **Step 6: Commit**

```bash
git add codewiki/src/be/pydantic_ai_backend.py
git add -f tests/test_decompose_on_overflow.py
git commit -m "feat(backend): reactively decompose modules that overflow the output cap"
```

---

## Task 5: Close the 3 gaps end-to-end and reconcile the wiki

This task runs the new feature against the real target repo `codebase-memory-mcp` (its `codewiki-docs/` is currently the restored, consistent 61-module state) and regenerates the wiki. It is operational (no new unit tests).

**Files:**
- Use: `/tmp/fill_gaps.py` (the isolated gap-fill script from this session)
- Output: `codebase-memory-mcp/codewiki-docs/` (gap docs, `module_tree.json`, `index.html`, `metadata.json`)

- [ ] **Step 1: Update the gap-fill script to rely on the engine feature**

Edit `/tmp/fill_gaps.py`:
- **Remove** the `is_complex_module` monkeypatch line `_pab.is_complex_module = lambda *a, **k: False` (and its comment). The engine now decomposes reactively, and multi-file gaps should decompose proactively via the unchanged `is_complex_module`.
- Keep `EXCLUDE = ["vendored", "grammars"]` and the `agent_instructions={"exclude_patterns": EXCLUDE}`.
- Keep the `overview.md` holdout and the per-gap `run_module_agent` loop.
- **Add metadata regeneration in-run:** inside `main()`, after the gap loop and the `overview.md` restore (just before `print(">> DONE")`), append:

```python
    gen.create_documentation_metadata(working_dir, components, len(leaf_nodes))
    print(">> regenerated metadata.json", flush=True)
```

  (`create_documentation_metadata(self, working_dir, components, num_leaf_nodes)` lives on `DocumentationGenerator`; `gen`, `working_dir`, `components`, `leaf_nodes` are all already in scope.)

- [ ] **Step 2: Snapshot the current docs (safety)**

```bash
cd codebase-memory-mcp/codewiki-docs
cp module_tree.json module_tree.json.pretask5
cp metadata.json metadata.json.pretask5
```

- [ ] **Step 3: Run the gap-fill (background; ~parse + 3 module agents)**

```bash
cd knowledgeLoop
CODEWIKI_NO_KEYRING=1 .venv/bin/python /tmp/fill_gaps.py > /tmp/fill_gaps3.log 2>&1 &
```
Watch `/tmp/fill_gaps3.log`. Expected: parse ~2.7k components; each gap either writes a single doc (fits) or logs the escalation warning and then writes a parent doc + sub-module docs. `overview.md` restored at the end; `>> DONE`.

- [ ] **Step 4: Verify every tree node now resolves to a doc**

```bash
cd codebase-memory-mcp
.venv/bin/python - <<'PY'
import json, os   # stdlib only
wd = "codewiki-docs"
tree = json.load(open(os.path.join(wd, "module_tree.json")))
def resolve(name):
    seen=set(); cands=[]
    for v in [name, name.replace(' ','_'), name.replace(' ','-'), name.replace(' ','')]:
        for c in (v, v.lower()):
            if c not in seen: seen.add(c); cands.append(c+'.md')
    return any(os.path.exists(os.path.join(wd, c)) for c in cands)
def walk(t, path=()):
    miss=[]
    for k,v in t.items():
        if v.get('components') and not resolve(k): miss.append('/'.join(path+(k,)))
        miss += walk(v.get('children') or {}, path+(k,))
    return miss
missing = walk(tree)
print("STILL MISSING:", missing or "none — all nodes documented")
PY
```
Expected: `none — all nodes documented` (the 3 gaps now resolve; Rust Resolver may appear as a parent with sub-modules).

- [ ] **Step 5: Regenerate metadata and index.html from the updated tree**

```bash
cd knowledgeLoop
CODEWIKI_NO_KEYRING=1 .venv/bin/python - <<'PY'
from codewiki.cli.html_generator import HTMLGenerator
REPO = "codebase-memory-mcp"
DOCS = REPO + "/codewiki-docs"
g = HTMLGenerator()
info = g.detect_repository_info(REPO)
g.generate(output_path=DOCS + "/index.html", title=info["name"],
           repository_url=info["url"], github_pages_url=info["github_pages_url"],
           docs_dir=DOCS)
print("index.html regenerated")
PY
```
`metadata.json` was already regenerated in-run by the line added to `/tmp/fill_gaps.py` in Step 1 (`gen.create_documentation_metadata(...)`), so no separate call is needed here.

- [ ] **Step 6: Confirm the wiki is consistent and commit nothing in this repo**

```bash
cd codebase-memory-mcp/codewiki-docs
grep -oE 'Rust Resolver|Core Infrastructure|TypeScript/JavaScript Resolver' index.html | sort -u
ls -1 *.md | wc -l   # > 61 (gaps + any sub-docs)
```
Expected: the three modules appear in `index.html`; doc count increased. (The target repo's `codewiki-docs/` is untracked there; no commit in `knowledgeLoop` for this step.)

---

## Task 6: Document the option and run the full suite

**Files:**
- Modify: `docs/findings-and-practices.md`
- Test: full suite

- [ ] **Step 1: Add a note to findings-and-practices.md**

Under "Recommended practices" (or "Honest limits"), add:

```markdown
- **Small-output models now self-heal oversized modules.** `ModelProfile`'s
  `decompose_on_overflow` (default on) makes a module whose single-doc write
  exceeds the output cap retry in decompose mode instead of becoming a gap.
  Disable per model with `config set-model <id> --no-decompose-on-overflow`.
  The subscription (claude-code/codex) path is inert here, as with output cap.
```

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -q`
Expected: PASS (all tests).

- [ ] **Step 3: Commit**

```bash
cd knowledgeLoop
git add docs/findings-and-practices.md
git commit -m "docs: note decompose_on_overflow option for small-output models"
```

---

## Self-Review notes (for the implementer)

- If `PydanticAIBackend.__init__`'s `create_fallback_models` raises in the test environment, the Task 4 test already monkeypatches it to a no-op; do not call the real LLM anywhere in tests.
- If `--no-decompose-on-overflow` is not yet a recognized `config set-model` flag, the override still works programmatically via the profile registry/override dict; wiring a CLI flag is optional polish, not required for the feature (out of scope for this plan).
- Acceptance for the whole plan: new tests pass, existing suite green, and the three `codebase-memory-mcp` modules resolve to docs in a consistent `index.html`.
