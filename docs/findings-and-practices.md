# Findings & Practices

Distilled, durable lessons from running this engine (CodeWiki) on a real codebase
with a small-output model, and from building the model-agnostic framework that
now encodes those lessons. Read this before operating the engine on a new model
or debugging a generation run — it captures what isn't obvious from the code.

## Context

We documented a ~345-file C codebase (`codebase-memory-mcp`) with **DeepSeek**
(`deepseek-chat`, ~8K output cap) through an OpenAI-compatible litellm gateway:
~3.2 hours, **61/64 module docs (95%)**. That run surfaced the findings below and
motivated the `ModelProfile` framework (`codewiki/src/be/model_profiles.py`).

The throughline: the agent loop was designed for **large-output, tool-disciplined
models (Claude-class)**. Pairing it with a small-output model exposes the seams.

## Failure modes & root causes

1. **Input overflow (~1M tokens).** When clustering is skipped, "whole-repo mode"
   reads every component into one context. *Fix:* force clustering by keeping the
   per-module token threshold below the codebase's leaf-summary total — now
   automatic, since granularity is derived from the output cap.
2. **Request-limit pre-write loop.** The agent exhausts its request budget *before
   writing any file* (reading/exploring without converging). A true gap occurs only
   at the intersection **(a sub-module that never wrote) × (a parent that had already
   finished)** — see parent-recovery below.
3. **Output-cap overflow.** A single doc-write larger than the model's output cap is
   rejected. If it's a *redundant* write after the doc already exists → harmless. If
   it's the *first* write of an oversized doc → that doc is lost.

## Optimization learnings (the counterintuitive part)

1. **Parent-recovery.** When a sub-module agent fails, the parent module agent often
   **back-fills the missing doc afterward** — *if the parent is still active*. So
   **warnings ≠ gaps**; most failures self-heal.
2. **Fail fast — do not raise the request limit.** Because the parent recovers, a
   stuck sub-agent should *bail quickly*. Raising the limit (we tried 50→200) just
   wastes ~7–8 min per stuck module before it quits; the outcome is identical.
   Budgets should be **low and fail-fast**, especially for sub-agents.
3. **Derive granularity from the output cap**, don't guess: `leaf ≈ cap×0.85`,
   `cluster ≈ cap×1.4`. Too-large granularity → first-write overflow → gaps.
4. **Cost is driven by loop *wandering*, not module size.** A small module took
   11 min; a bigger one took 2. Reducing tool-call churn matters more than content.
5. **Where docs complete, quality is high** — valid Mermaid, accurate cross-links.
   The Mermaid validator is accurate; the ceiling is the model's output window, not
   the framework.

## Debugging / process lessons

- **Never conclude from mid-run state.** We twice labeled modules "gaps" from a
  snapshot; they self-healed by the end. Verify findings against the **finished run**.
- **The intuitive fix usually treats the symptom.** "Hit a limit → raise the limit"
  and "add a retry" both missed the real mechanic. The fix came from understanding
  the system (parent-recovery, the pre-write loop). Root-cause before patching.
- **Instrument before fixing an unconfirmed loop.** `run_module_agent` logs a
  per-module tool-call histogram (read-id reuse, edit counts) that distinguishes
  "repeated reads" from "Mermaid-fix cycles." The true loop cause was never confirmed
  by trace, so the loop *fix* remains gated on that data.

## Recommended practices

- **Configure per model via the profile, not by hand.** `config set --main-model X`
  auto-applies output cap, request budget, granularity, and token-param style. For a
  gateway-renamed or unknown id, pin it:
  `config set-model <id> --output-cap 8192 --token-param-style max_tokens`.
- **Scope the run.** Exclude vendored code, tests, generated grammars, and non-core
  dirs with `--exclude`; focus the real source. Tighter scope = better signal, less
  cost. (Note: `--focus` is only a prompt hint — it does *not* restrict the file set.)
- **Read the diagnostics** in verbose logs to spot wandering/looping modules early.
- **Don't fight the output cap by raising limits.** Let granularity split the work,
  and let parent-recovery + the missing-doc sweep fill gaps.
- **For best quality, use a large-output model** (e.g. Claude Sonnet, 64K). Within a
  small-output gateway, DeepSeek + the profile is the practical best, capped ~95%.
- **Small-output models now self-heal oversized modules.**
  `ModelProfile.decompose_on_overflow` (default on) makes a module whose single-doc
  write exceeds the output cap retry in *decompose* mode instead of becoming a gap.
  It is a per-model profile setting (override via the profile registry or a
  `resolve_profile` override). The subscription (claude-code/codex) path is inert
  here, as it is for the output cap.

## Model-agnostic framework (how the learnings are encoded)

`codewiki/src/be/model_profiles.py` makes per-model operational parameters
declarative. A `ModelProfile` (output cap, request budget, granularity, token-param
style, max depth, temperature) is resolved from provider defaults + a per-model
`REGISTRY` + optional overrides; `Config.__post_init__` applies it with
**explicit-CLI-values-win** precedence. The six stages:

| Stage | What it adds |
|---|---|
| 0 | De-hardcode the operational knobs into `Config` |
| 1 | Diagnostics (per-module tool-call histogram) |
| 2 | Registry + resolver + auto-config (the backbone; folds in fail-fast budget + granularity-from-cap) |
| 3 | Per-model overrides + `config set-model` / resolved `config show` |
| 4 | Missing-doc sweep (deterministically fills gaps) |
| 5 | Opt-in concurrency (`--concurrency N`, per-module tree isolation + merge) |
| 6 | Tuning knobs (granularity factors; separate sub-agent budget) |

Backed by 38 tests under `tests/`.

## Honest limits

- **Output cap is a hard quality ceiling.** A model cannot produce a coherent
  single-write doc larger than its cap; the framework makes that failure *graceful*
  (split + recovery), not absent. The one-line remedy is "use a bigger-output model."
- **The subscription path (Claude Code / Codex) cannot be probed or numerically
  bounded.** Output cap / request limit are inert there — only granularity and
  max-depth are levers.
- **The loop-efficiency fix is gated on live diagnostic data.** Read-deduplication is
  unsafe without per-agent-run scoping (sub-agents have separate contexts), so only
  the tuning infrastructure is in place; the actual fix awaits Stage 1 data.
