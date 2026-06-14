# Reactive decompose-on-overflow for small-output models

- **Date:** 2026-06-13
- **Status:** Approved (design) — pending implementation plan
- **Author:** CodeWiki Contributors (with Claude)

## 1. Problem

CodeWiki's per-module agent writes a module's documentation as a single
document via the `str_replace_editor` "create" tool call. On a **small-output
model** (e.g. `deepseek-chat`, ~8K output cap) the markdown for a large module
can exceed the model's output token limit. The response is truncated mid
tool-call, pydantic-ai raises `IncompleteToolCall`, and **no doc file is
written** — the module becomes a permanent gap.

This was reproduced empirically on `codebase-memory-mcp` with DeepSeek: three
`lsp_support` leaf modules — **Rust Resolver** (12 components, multi-file),
**Core Infrastructure** (8), **TypeScript/JavaScript Resolver** (3) — all failed
with:

```
IncompleteToolCall: Model token limit (provider default) exceeded while
generating a tool call, resulting in incomplete arguments.
```

The effective request was correct (`max_tokens: 8192`, the resolved profile's
output cap), so this is the **hard output-cap ceiling** described in
`docs/findings-and-practices.md`, not a misconfiguration.

### Why the current decomposition trigger is insufficient

The engine already has a decomposition path: `is_complex_module(components,
core_component_ids)` (`codewiki/src/be/utils.py`) returns true when a module's
components span **more than one file**, in which case `run_module_agent` builds
the *complex* agent (with `generate_sub_module_documentation_tool`) that breaks
the module into sub-modules. This file-count proxy is crude:

- It **misses** single-file modules whose doc still overflows the cap (the
  failure mode above for any single-file oversized module).
- It **over-fires** on multi-file modules whose combined doc would fit fine.

It is also not the cause of the Rust Resolver gap: Rust Resolver is multi-file,
so it *already* routes to decompose; its original gap was *incomplete*
decomposition under a shared request budget / parent-already-finished race — the
single-doc overflow only occurs when leaf generation is forced.

## 2. Goal

Make oversized modules **succeed** on small-output models by reactively falling
back to decomposition when (and only when) a single-doc write actually
overflows the output cap — expressed as a declarative, per-model option in the
existing model-profile framework. Then use it to close the three known gaps and
restore a consistent wiki (every module documented; the previously-missing
modules now resolve to docs, with oversized ones decomposed into sub-modules).

## 3. Design decisions (agreed)

| Decision | Choice | Rationale |
|---|---|---|
| **Trigger** | Reactive fallback: try single doc, on overflow retry as decompose | Precise — only decomposes modules that genuinely overflow; no fragile size estimation; small modules keep clean single docs |
| **Config surface** | `ModelProfile.decompose_on_overflow: bool = True`, per-model/CLI override | Fits the model-agnostic framework (`model_profiles.py`); declarative, overridable, default-on |
| **Existing `is_complex_module`** | **Keep** as the proactive (multi-file) trigger; add reactive fallback alongside | Lowest risk; the reactive path covers only what the proxy misses (single-file overflow) |
| **Scope** | Build feature + tests, then close the 3 gaps and reconcile the wiki end-to-end | Gaps are the real-world acceptance test |

## 4. Detailed design

### 4.1 `ModelProfile.decompose_on_overflow`

Add a boolean field to the `ModelProfile` dataclass
(`codewiki/src/be/model_profiles.py`):

```python
decompose_on_overflow: bool = True
```

A dataclass default of `True` automatically covers every `PROVIDER_DEFAULTS`
entry and every `REGISTRY` entry without editing each constructor. The existing
`_merge(base, match, user_override)` and `resolve_profile(...)` flow already
propagate per-model registry values and user overrides, so
`config set-model <model> --no-decompose-on-overflow` (override key
`decompose_on_overflow: false`) works with no special handling. `Config`
retains the resolved profile as `self.profile` (`config.py:__post_init__`,
where `p = self.profile`), so the backend reads
`config.profile.decompose_on_overflow` directly — no new `Config` field or
back-fill required.

### 4.2 Reactive retry in `run_module_agent`

File: `codewiki/src/be/pydantic_ai_backend.py`, `run_module_agent`
(currently lines ~56–145).

**(a) Extract agent construction.** Lines 78–97 currently branch on
`is_complex_module(...)` to build either the complex agent
(`[read_code_components_tool, str_replace_editor_tool,
generate_sub_module_documentation_tool]` + `format_system_prompt`) or the leaf
agent (`[read_code_components_tool, str_replace_editor_tool]` +
`format_leaf_system_prompt`). Factor this into a helper:

```python
def _build_agent(self, module_name, *, complex_: bool) -> Agent:
    ...  # returns the complex or leaf Agent exactly as today
```

The initial agent is chosen as today: `complex_=is_complex_module(components,
core_component_ids)`.

**(b) Escalate on overflow.** The existing `except Exception as e` block
(lines 127–144) already handles "agent raised *after* writing the doc" (doc file
exists → treat as complete). Insert the reactive fallback **before the final
`raise`**, guarded by all of:

1. `isinstance(e, IncompleteToolCall)` — the overflow signal
   (`from pydantic_ai.exceptions import IncompleteToolCall`; observed class in
   the reproduced traceback).
2. the doc file does **not** exist (`not os.path.exists(docs_path)`) — i.e. the
   write never completed; distinguishes this from the existing
   "raised-after-writing" case.
3. `config.profile.decompose_on_overflow` is true.
4. we have not already escalated this call (a local `escalated` flag) — the
   current agent was the **leaf** agent (if it was already complex, decomposing
   again is a no-op; fall through to existing handling).

When all hold: log the escalation, rebuild with `_build_agent(module_name,
complex_=True)`, reset the per-run state needed for a clean retry (fresh `deps`
/ reload `module_tree` so a partial first attempt cannot leak in), and re-run
the agent **once**. On success, persist `deps.module_tree` and return as the
normal path does. If the retry itself raises, fall through to the existing
error handling (`raise`).

**Recursion / bounding.** The complex agent documents sub-modules through their
own `run_module_agent` invocations, so a sub-module that *also* overflows is
handled at its own level by the same fallback. Depth is bounded by the existing
`max_depth`; the per-call `escalated` flag prevents an infinite leaf→complex
loop at a single level.

**No orchestrator change.** `documentation_generator.py` is untouched; the
behavior is entirely inside the backend.

### 4.3 Subscription backend

`caw_backend.py` (the `claude-code` / `codex` path) is **out of scope**. Per
`docs/findings-and-practices.md` the subscription path is inert for output cap /
request limit and has no equivalent `IncompleteToolCall` overflow signal. The
flag defaults `True` there but simply never fires.

## 5. Closing the gaps + wiki reconciliation (end-to-end)

After the feature lands:

1. Run the three-gap fill in isolation (the proven pattern: hold out
   `overview.md` so `run_module_agent`'s early-return guard does not short
   circuit, then call `run_module_agent` for each gap node against the restored
   nested `module_tree.json`). With the feature active: multi-file gaps
   decompose proactively; single-file gaps that overflow decompose reactively.
   The isolated run gives each gap a fresh request budget and no parent race, so
   decomposition can complete (the earlier interrupted run was already producing
   valid Rust Resolver sub-docs).
2. The complex path grafts new sub-modules into `deps.module_tree` and saves it,
   so `module_tree.json` gains the sub-structure automatically.
3. **Regenerate `index.html` and `metadata.json`** from the updated tree
   (`metadata` via `DocumentationGenerator.create_documentation_metadata`; HTML
   via the existing GitHub-Pages/`_run_html_generation` path in
   `codewiki/cli/adapters/doc_generator.py`) so navigation and stats include the
   new docs.

**Acceptance:** the three previously-missing modules are documented (oversized
ones as a parent doc plus decomposed sub-module docs), so **every node in
`module_tree.json` — which now expands beyond the original 64 as gaps
decompose — resolves to a doc**; `index.html` browses the new sub-docs;
`metadata.json` statistics are consistent with the on-disk docs.

## 6. Testing

New unit tests (added under `tests/`; note `tests/` is gitignored and tracked
only via `git add -f`):

1. **Escalation happens:** stub backend whose leaf agent run raises
   `IncompleteToolCall` and whose complex agent run succeeds (writes the doc) →
   assert exactly one escalation, the complex toolset was used, and the module
   is returned as complete.
2. **Flag gates it:** same stub with `decompose_on_overflow=False` → assert the
   exception re-raises and no escalation occurs.
3. **Existing behavior preserved:** overflow raised *after* the doc file exists
   → still treated as complete (no escalation, no regression of the current
   `pydantic_ai_backend.py` lines 134–141 path).
4. **Profile default:** `resolve_profile(...)` yields `decompose_on_overflow ==
   True` by default and honors a `False` user override.

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider` (pyproject sets
`--cov`, so `pytest-cov` must be installed or append `--no-cov`).

## 7. Files touched

| File | Change |
|---|---|
| `codewiki/src/be/model_profiles.py` | add `decompose_on_overflow: bool = True` to `ModelProfile` |
| `codewiki/src/be/pydantic_ai_backend.py` | extract `_build_agent`; reactive escalation in `run_module_agent` except block |
| `tests/` (new test file, `git add -f`) | unit tests 1–4 above |
| `docs/findings-and-practices.md` | short note documenting the new option (small-model practice) |
| `codewiki-docs/` of `codebase-memory-mcp` (target repo, not this repo) | regenerated gap docs + tree + index.html + metadata |

## 8. Risks & open notes

- **Decomposition completeness** for Rust Resolver depends on it finishing
  within the request budget in the isolated run; mitigated by fresh per-module
  budget and no parent race. If it still stalls, the request budget for the
  isolated fill can be raised for that run only.
- **Sub-doc naming** is agent-chosen (e.g. `Rust Resolver - Macro Handling.md`);
  `_resolve_child_docs_path` already tolerates name variants, and index
  regeneration reads the saved tree, so navigation stays consistent.
- **No behavior change for big-output models** — they virtually never raise the
  overflow, so the fallback is dormant.
