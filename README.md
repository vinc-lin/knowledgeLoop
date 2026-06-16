<h1 align="center">KnowledgeLoop</h1>

<p align="center">
  <strong>The knowledge layer that makes AI agents trustworthy on real codebases.</strong>
</p>

<p align="center">
  Grounded, freshness-aware code intelligence • Architecture-aware docs fused with a verifiable code graph • Built to close the loop
</p>

<p align="center">
  <a href="https://python.org/"><img alt="Python version" src="https://img.shields.io/badge/python-3.12+-blue?style=flat-square" /></a>
  <a href="./LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" /></a>
</p>

<p align="center">
  <a href="./docs/INTRODUCTION.md"><strong>Vision</strong></a> •
  <a href="./docs/SETUP.md"><strong>Setup &amp; Run</strong></a> •
  <a href="./docs/MVP.md"><strong>MVP Spec</strong></a> •
  <a href="./docs/CODEWIKI.md"><strong>CodeWiki Engine</strong></a> •
  <a href="./DEVELOPMENT.md"><strong>Development</strong></a>
</p>

<p align="center">
  🔁 New here? Start with the <a href="./docs/INTRODUCTION.md"><strong>vision introduction&nbsp;→</strong></a>
</p>

---

## What is KnowledgeLoop?

**KnowledgeLoop** turns a large codebase into living, architecture-aware knowledge and
serves it to AI agents through a single grounded interface — so they get source-backed,
freshness-checked answers instead of confident guesses. The goal is to **close the loop**:
agents read what the system knows, act on it, and feed their results back, so understanding
compounds instead of decaying. See the [**vision introduction**](./docs/INTRODUCTION.md)
for the full picture and diagram.

It works in three stages — **produce → bridge → consume** — with a fourth, **feed back**,
on the roadmap:

| Stage | What | Status |
|---|---|---|
| **Produce** | [CodeWiki](./docs/CODEWIKI.md) generates a holistic, architecture-aware wiki (Markdown + Mermaid) from a repo across 8 languages | ✅ Built |
| **Bridge** | Fuse the wiki with a verifiable code graph (Codebase-Memory-MCP) into a Wiki↔Graph map | ✅ Built |
| **Consume** | The `repo_memory` MCP server answers grounded, freshness-aware questions via 12 tools | ✅ Built |
| **Feed back** | Agents write execution results back into the knowledge base | 🟡 Roadmap |

> The internal Python package and CLI are still named **`codewiki`** — KnowledgeLoop is
> built on the CodeWiki foundation and keeps that name intentionally.

---

## Quick start

**Produce** a wiki for a repo (the `codewiki` CLI):

```bash
cd /path/to/your/project
codewiki generate --output ./wiki-docs --github-pages
```
Provider setup and the full CLI reference: [`docs/CODEWIKI.md`](./docs/CODEWIKI.md).

**Consume** it with grounded, freshness-aware answers (the `repo_memory` MCP server, stdio):

```bash
repo-memory          # or:  python -m repo_memory
```
From-zero install, MCP-client registration (incl. Claude Code), and the read-only-corpus
testing recipe: [`docs/SETUP.md`](./docs/SETUP.md).

---

## Documentation

| Doc | What |
|---|---|
| [Vision](./docs/INTRODUCTION.md) | Why KnowledgeLoop, the close-the-loop idea, modules & stages (start here) |
| [Setup & Run](./docs/SETUP.md) | Install, generate, launch the MCP server, use it in Claude Code |
| [MVP Spec](./docs/MVP.md) | The `repo_memory` grounded-MCP facade: architecture, the 12 tools, guarantees |
| [Close-the-loop workflow](./docs/close-loop-workflow.md) | Produce → bridge → consume → feed-back narrative |
| [CodeWiki engine](./docs/CODEWIKI.md) | The doc-generation engine: providers, CLI commands, benchmarks, paper |
| [Development](./DEVELOPMENT.md) | Architecture map, extending, debugging |

---

## Built on CodeWiki

KnowledgeLoop's *produce* stage is [CodeWiki](https://github.com/FSoft-AI4Code/CodeWiki)
([paper](https://arxiv.org/abs/2510.24428)), copied verbatim as its foundation. The full
CodeWiki README — provider configuration, CLI reference, benchmarks, and citation — lives at
[`docs/CODEWIKI.md`](./docs/CODEWIKI.md).

## License

MIT — see [LICENSE](./LICENSE).
