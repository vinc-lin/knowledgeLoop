# Adoption Hook — Productize the Gated Nudge

**Status:** Approved (design)
**Date:** 2026-06-28
**Depends on:** lap-9 (merged `7c6f966`) — the validated `assisted` mechanism: an insufficiency-gated
soft nudge reached **53%** grounded-success (≈80% of the 67% ceiling, +40pp over control) by getting
the agent to call `find_related` itself, with no mandatory directive and no over-steering on local
tasks. Today that mechanism exists **only inside the eval harness**
(`repo_atlas/eval/adoption.py` = the gate, `repo_atlas/eval/runner.py` = the `NUDGE` text + the
`assisted` arm). This spec ships it as a real Claude Code mechanism.

## Context — the problem this solves

The eval proved adoption is solvable, but the proof lives in the test rig: the `assisted` arm
prepends a gated nudge to the *task prompt* before the agent acts. A real coding agent in a user's
repo gets none of that — it sees only the `find_related` MCP tool (the legibility layer, ~40%
natural adoption). To capture the measured 53% in real use, the gated nudge must fire in the live
agent loop. In Claude Code the faithful analog of "inject before the agent acts" is a
**`UserPromptSubmit` hook** (a skill is agent-invoked, which reintroduces the adoption gap we are
trying to close). So: productize the gate + nudge as a hook, reusing the existing `find_related`
retrieval.

## Goals

1. **One shared gate.** Lift the insufficiency gate + nudge text out of `eval/` into a product
   module so the eval and the product run the *same* code (DRY).
2. **A hook-callable entrypoint.** A `repo-atlas gate` CLI subcommand that reads a prompt, runs the
   gate, and prints the nudge iff local context is insufficient.
3. **A documented, opt-in hook.** A `UserPromptSubmit` config snippet (in
   `docs/applying-to-a-new-repo.md`) that wires `repo-atlas gate` so the nudge is injected at task
   start.
4. **Never disrupt the user.** The hook fails **open**: any error → no output, exit 0.

## Non-goals (YAGNI — explicitly out of scope)

- **No auto-inject.** Soft nudge only (the chosen, measured behavior); the agent forms its own
  `find_related` query. Auto-inject (the 67% ceiling) is a documented future escalation, not built.
- **No `PreToolUse` hook.** `UserPromptSubmit` (task start) is the faithful timing; the write-moment
  hook is not built.
- **No new retrieval infrastructure.** Reuse `find_related_units` / the `OfflineRetriever`.
- **Not auto-installed.** The hook is an opt-in documented config, like the MCP server setup.
- **No re-validation eval.** The mechanism is already measured (lap 9, 53%); this is an engineering
  translation, not a new experiment. (A one-off deployed-gate fidelity check is noted under Risks.)

## Design

### Component 1 — `repo_atlas/adoption.py` (new product module; DRY home for the gate)

Move the gate primitives out of `repo_atlas/eval/adoption.py` into a product module:

- `NUDGE: str` — the soft, conditional nudge text (moved verbatim from `eval/runner.py`; the eval
  imports it from here). No "MUST"/"FIRST" (it is the soft variant, not the mandatory STEER).
- `_present_in_tree(rel_or_name, work_dir) -> bool` — moved verbatim from `eval/adoption.py`
  (basename walk of the snapshot/work-tree, skipping `.git`).
- `async def gate_query_out_of_tree(query: str, work_dir: str, retriever, *, k: int = 5) -> bool`
  — the query-based core: `units = await retriever.retrieve(query, None, k)`; True iff the top hit's
  file is non-empty and **not** present under `work_dir`. (This is the existing gate logic, taking a
  raw query string instead of a `Task`.)
- `async def nudge_for(prompt: str, work_dir: str, retriever, *, k: int = 5) -> str | None`
  — returns `NUDGE` when `gate_query_out_of_tree(prompt, work_dir, retriever, k)` else `None`.
- `def is_coding_intent(prompt: str) -> bool` — cheap regex pre-filter: True iff the prompt looks
  like an implementation/change request (e.g. matches any of `implement|add |fix |use the existing|
  wire up|refactor|write a|create a|hook up|call the`), case-insensitive. Used to skip the retrieval
  on non-coding prompts.

`repo_atlas/eval/adoption.py` becomes a thin re-export: its `local_context_insufficient(task,
work_dir, retriever, *, k=5)` delegates to `gate_query_out_of_tree(task_query(task), work_dir,
retriever, k)`. `eval/runner.py` imports `NUDGE` from `repo_atlas.adoption`. No behavior change → the
existing eval/adoption + runner tests still pass.

### Component 2 — `repo-atlas gate` CLI subcommand (`repo_atlas/cli.py`)

A new subcommand the hook shells out to. Contract:

- **Input:** reads the `UserPromptSubmit` hook payload as JSON on **stdin** (`{"prompt": "...",
  "cwd": "...", ...}`); falls back to `--prompt TEXT` + `os.getcwd()` for testing. `work_dir` = the
  payload `cwd` (the user's repo).
- **Flow:** if `not is_coding_intent(prompt)` → print nothing, exit 0. Else build the retriever from
  config (`Store` + `GatewayEmbedder` + `OfflineRetriever`, as `eval-arms` does), run
  `nudge_for(prompt, work_dir, retriever)`, and print the nudge to **stdout** iff non-None.
- **Fail-open (the prime directive):** the entire body is wrapped so that **any** exception (missing
  index, unreachable embeddings endpoint, missing config, malformed stdin) results in **no stdout
  and exit 0**. A hook on the prompt path must never error or block.
- Flags: `--k` (gate depth, default 5), `--prompt` (test input).

### Component 3 — Hook config + docs

Add to `docs/applying-to-a-new-repo.md` an opt-in "adoption nudge" step with the snippet for the
user's `.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "repo-atlas gate" } ] }
    ]
  }
}
```

Documented prerequisites (same as the MCP server): the repos are indexed (`repo-atlas index --all`)
and the embeddings endpoint is reachable; otherwise the hook silently no-ops. Note the hook
complements — does not replace — the `find_related` MCP server (the nudge tells the agent to call
that tool).

## Data flow

```
user prompt
  → UserPromptSubmit hook (.claude/settings.json)
  → `repo-atlas gate`  (stdin JSON: prompt, cwd)
        → is_coding_intent? no → (silent)
        → yes → embed prompt → find_related across ALL repos (repos=None)
              → top hit's file out-of-work-tree? no → (silent)
                                                  yes → print NUDGE
  → hook stdout injected as context at task start
  → agent reads nudge → calls find_related MCP tool (its own query)
  → retrieves the cross-repo helper → uses it
```

## Components & interfaces (summary)

| Unit | File | Responsibility | Depends on |
|---|---|---|---|
| `NUDGE`, `_present_in_tree`, `gate_query_out_of_tree`, `nudge_for`, `is_coding_intent` | `repo_atlas/adoption.py` (new) | the shared gate + nudge | `retrieve.find_related_units` (via retriever) |
| `local_context_insufficient` (delegator) | `repo_atlas/eval/adoption.py` | eval-facing wrapper (Task → query) | `repo_atlas.adoption`, `eval.tasks.task_query` |
| `repo-atlas gate` | `repo_atlas/cli.py` | hook entrypoint, pre-filter, fail-open | `repo_atlas.adoption`, config, store/embedder |
| hook config + docs | `docs/applying-to-a-new-repo.md` | opt-in wiring | Claude Code `UserPromptSubmit` |

## Error handling

Fail-open at the CLI boundary: wrap the whole `gate` body; on any error print nothing, exit 0. The
gate depends on a built index + a reachable embeddings endpoint; when either is absent it no-ops
(never errors). This is the single most important property — a prompt-path hook that errors or hangs
would degrade every session.

## Testing (judge-free, no `claude` / no quota)

1. `is_coding_intent`: True for "implement X / add a Y / use the existing Z / fix the W"; False for
   "what does this function do?" / "explain the architecture".
2. `gate_query_out_of_tree` + `nudge_for` (reuse the lifted gate tests, now query-based): top hit
   out-of-tree → nudge; in-tree → None; no hits / no retriever → None.
3. `repo-atlas gate` CLI via a stub retriever: stdin `{"prompt":"add … use the existing helper",
   "cwd": <tmp>}` with an out-of-tree top hit → stdout == NUDGE; an in-tree top hit → empty; a
   non-coding prompt → empty (no retrieval attempted); **a retriever that raises → empty + exit 0**
   (fail-open).
4. Eval regression: `tests/test_eval_adoption.py` + `tests/test_eval_runner.py` still pass after the
   lift (the eval wrapper + `NUDGE` import are unchanged in behavior).

Run new/changed unit tests per-file (`-p no:cacheprovider --no-cov`); `git add -f` new test files.

## Verification (end-to-end)

1. Unit tests green.
2. Manual hook test in a throwaway repo wired to the libxcam-ocl substrate: a cross-repo prompt
   ("add per-handler FPS logging using the project's profiling helper") → the nudge appears in
   context and the agent calls `find_related`; a purely-local prompt → no nudge. (Mirrors the lap-8
   over-steering check, now in the live hook.)
3. Confirm fail-open: with the embeddings endpoint down, the same prompt → hook no-ops, the session
   proceeds normally.
4. Document the verified config in `docs/applying-to-a-new-repo.md`.

## Risks

- **Hook contract drift.** The exact `UserPromptSubmit` payload shape (stdin JSON keys) and the
  "stdout-is-injected-as-context" behavior must be confirmed against the current Claude Code docs in
  the implementation plan. Mitigation: the `--prompt` flag keeps the CLI testable independent of the
  hook contract; the JSON-stdin reader tolerates missing keys (→ fail-open).
- **Deployed-gate fidelity.** The eval gate used a *focused* `retrieval_query`; the hook uses the
  *raw* user prompt as the gate query. The gate only needs a binary out-of-tree decision (not to
  rank a specific helper), so a verbose query is acceptable — but a deployed-vs-eval gate agreement
  check is a sensible one-off follow-up (out of scope here).
- **Per-prompt retrieval cost.** Bounded by `is_coding_intent` (no retrieval on non-coding prompts);
  acceptable since `find_related` is a sub-second local search.
- **Fail-open hides misconfiguration.** A silently-no-op hook could mask "index not built / server
  down." Mitigation: `repo-atlas gate --prompt "..."` run by hand surfaces errors for debugging
  (only the *hook path* swallows them).
