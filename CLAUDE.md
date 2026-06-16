# CLAUDE.md

Guidance for AI agents working in this repository. Keep it concise — for deep
detail see `README.md` (users) and `DEVELOPMENT.md` (architecture, extending,
debugging). This file captures the high-signal, non-obvious essentials.

- `docs/findings-and-practices.md` — operational learnings from real generation runs
  (the source distilled into the Gotchas below).
- `docs/superpowers/specs/` + `docs/superpowers/plans/` — design specs & implementation
  plans for recent/in-flight features (canonical doc filenames, decompose-on-overflow,
  body-link consistency).

## What this is

**knowledgeLoop** is a foundation copied **verbatim from CodeWiki**. The internal
Python package and CLI are still named **`codewiki`** — this is intentional and
should not be renamed without an explicit decision.

CodeWiki generates holistic, architecture-aware documentation for large
codebases: parse a repo (tree-sitter, 9 languages) → cluster it into a module
hierarchy → run a recursive per-module agent loop → emit Markdown + Mermaid
diagrams + a browsable HTML wiki. It is multi-provider (OpenAI-compatible,
Anthropic, Bedrock, Azure, plus subscription via Claude Code / Codex).

**Future direction (not yet built):** agents and skills layered on top of this
knowledge base that consume the generated knowledge and feed execution results
back — "closing the loop." Today the repo is just that foundation.

## Setup

- **Python 3.12+ is required** (`pyproject.toml` `requires-python = ">=3.12"`).
- **Node.js ≥14 is required** for Mermaid diagram validation (`mermaid-py`, used by the
  agent's `str_replace_editor`); without it those checks can't run. (`pyproject.toml [external]`.)
- This project ships **no committed `.venv`**; create one:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"   # runtime + tests (pytest/cov/asyncio) + lint (ruff/black/mypy)
```

## Common commands

```bash
# Tests (pyproject enables --cov, so pytest-cov must be installed;
# otherwise append --no-cov). -p no:cacheprovider avoids writing .pytest_cache.
.venv/bin/python -m pytest tests/ -p no:cacheprovider

# Lint / format / type-check (configs in pyproject; line-length 100, target py312).
.venv/bin/ruff check codewiki/      # lint
.venv/bin/black codewiki/           # format (use --check in CI)
.venv/bin/mypy codewiki/            # type-check (config is permissive)

# Configure a provider/model (CODEWIKI_NO_KEYRING=1 forces file-based creds in
# headless environments without a system keychain).
CODEWIKI_NO_KEYRING=1 .venv/bin/codewiki config set \
  --provider openai-compatible --api-key KEY --base-url URL/v1 \
  --main-model deepseek-chat --cluster-model deepseek-chat
CODEWIKI_NO_KEYRING=1 .venv/bin/codewiki config show      # resolved profile + caw warnings
CODEWIKI_NO_KEYRING=1 .venv/bin/codewiki config validate  # tests gateway connectivity

# Generate docs for the current repo (run from the target repo's directory).
codewiki generate --output ./wiki-docs --github-pages --verbose
codewiki generate --concurrency 4   # opt-in parallel module processing (default 1)
```

## Architecture orientation

- `codewiki/cli/` — CLI surface: `commands/` (config, generate), `adapters/`,
  `config_manager.py`, `models/config.py` (persistent `Configuration`).
- `codewiki/src/be/` — the engine:
  - `dependency_analyzer/` — tree-sitter parsing → dependency graph + components.
  - `cluster_modules.py` — groups components into the module tree (LLM clustering
    above a token threshold; whole-repo mode below it).
  - `documentation_generator.py` — orchestrates per-module generation, the
    missing-doc sweep, and (opt-in) concurrent processing.
  - `backend.py` + `pydantic_ai_backend.py` (API path) + `caw_backend.py`
    (subscription path via the `claude`/`codex` CLI) — two `LLMBackend` impls.
  - `agent_tools/` — the agent's tools (`read_code_components`,
    `str_replace_editor` with Mermaid validation, `generate_sub_module_documentations`).
  - `llm_services.py` — model/client construction and token-param handling.
- `codewiki/src/fe/` — optional web app. `codewiki/src/config.py` — runtime `Config`.

See `DEVELOPMENT.md` for the full map.

## Model-agnostic framework (recent, important)

`codewiki/src/be/model_profiles.py` makes per-model operational parameters
declarative instead of hardcoded. A `ModelProfile` (output cap, request budget,
clustering granularity, token-param style, max depth, temperature) is resolved
from provider defaults + a per-model `REGISTRY` + optional user overrides via
`resolve_profile(provider, model, override)`. `Config.__post_init__` resolves and
back-fills it automatically with **explicit-CLI-values-win** precedence.

- Switch models with a one-liner: `config set --main-model qwen3` — granularity,
  request budget, and token-param style follow the profile (no manual token math).
- Per-model overrides: `config set-model <model> --request-limit N --leaf-granularity N`.
- Clustering granularity is **derived from the model's output cap**
  (`leaf ≈ cap*0.85`, `cluster ≈ cap*1.4`; constants in `model_profiles.py`).
- **Subscription path (`claude-code`/`codex`) is inert** for output cap / request
  limit / token-param style — only granularity + max_depth are levers there.

## Gotchas & conventions

- **`tests/` is gitignored** (inherited `.gitignore`). The test suite is tracked
  only because it was force-added; new test files need `git add -f`.
- `pytest` will error without `pytest-cov` (pyproject sets `--cov`); install it or
  pass `--no-cov`.
- **Small-output models (e.g. DeepSeek, 8K output):** docs that exceed the cap on a
  single write fail; the profile sizes granularity to the cap so modules split.
  Request budgets are intentionally **fail-fast** — a stuck sub-agent should bail so
  the parent module agent back-fills its doc (parent-recovery). Don't "fix" failures
  by raising the request limit.
- Diagnostics: `run_module_agent` logs a per-module tool-call histogram (read-id
  reuse, edit counts) — use it to trace non-converging agent loops.
- Generated doc filenames are **canonicalized at the end of generation** (H1-derived
  names + path-separator sanitization, in `documentation_generator.py`); the HTML nav
  slug and in-doc links must round-trip with it (URL-encoded fetch). Change one, keep all
  three consistent — see `docs/superpowers/specs/2026-06-14-*`.
- Match the surrounding code style; keep the `codewiki` package/CLI names as-is.
