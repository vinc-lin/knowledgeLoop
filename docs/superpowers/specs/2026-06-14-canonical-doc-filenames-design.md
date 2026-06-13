# Canonical doc filenames + nav consistency

- **Date:** 2026-06-14
- **Status:** Approved (design) — pending implementation plan
- **Author:** vinc (with Claude)

## 1. Problem

CodeWiki's browsable wiki (`index.html`) builds each nav link and resolves each
in-doc cross-reference link to **exactly `${node-key}.md`** (the module-tree key
plus `.md`) — see `codewiki/templates/github_pages/viewer_template.html`
(`buildNavItem` sets `data-file = \`${key}.md\``; `loadDocument` fetches it; a
content click-handler routes `.md` body links through the same `loadDocument`).

The doc-writing agent is *instructed* to create `${module_name}.md`
(`prompt_template.py:16,34`), but small/unreliable models deviate:

- **Slugified** names: `Go Resolver` → `go_resolver.md`, `Rust Resolver` →
  `Rust_Resolver.md`, `Proc Macro Synthesis` → `proc_macro_synthesis.md`.
- **Arbitrary** names: `C# Resolver` → `cs_lsp.md`, `TypeScript/JavaScript
  Resolver` → `ts_lsp.md`.

When the filename ≠ `${key}.md`, the nav link and any raw-name cross-reference
link 404. This is a pre-existing CodeWiki quirk (it already affects the original
resolver docs), independent of any single generation run.

### Investigation results (on `codebase-memory-mcp/codewiki-docs`, 69 nodes)

- **8 files** currently mismatch their node key and need renaming:
  `go_resolver.md`→`Go Resolver.md`, `Java_Resolver.md`→`Java Resolver.md`,
  `Kotlin_Resolver.md`→`Kotlin Resolver.md`, `PHP_Resolver.md`→`PHP Resolver.md`,
  `Rust_Resolver.md`→`Rust Resolver.md`,
  `proc_macro_synthesis.md`→`Proc Macro Synthesis.md`,
  `cs_lsp.md`→`C# Resolver.md`,
  `ts_lsp.md`→`TypeScript_JavaScript Resolver.md`.
- Matching each node to its file by **normalized name** (alphanumeric, lowercased)
  resolves 67/69; an **H1-title fallback** resolves the remaining 2 arbitrary
  names (their first `# ` heading contains the node key: "C# Resolver (cs_lsp)",
  "TypeScript/JavaScript Resolver Module"). **0 unresolved, 0 ambiguous, 0
  orphans.**
- Only **2 keys** contain special characters: `C# Resolver` (`#`) and
  `TypeScript/JavaScript Resolver` (`/`).
- `/mnt/x` is a **case-insensitive** Windows mount; GitHub Pages (deploy target)
  is **case-sensitive** — so renames must use the *actual* on-disk filename and
  produce the *exact* canonical casing.

## 2. Goal

Make each module's doc reliably reachable from the wiki by **canonicalizing doc
filenames to the node key** (deterministic, not trusting the LLM), plus a small
nav-side encoding fix — and apply it to the existing `codebase-memory-mcp` wiki.

## 3. Design decisions (agreed)

| Decision | Choice |
|---|---|
| **Strategy** | Enforce a canonical filename (override agent naming); don't record agent-chosen names |
| **Mechanism** | An end-of-run **canonicalization pass** (tree-walk, mirrors the `_fill_missing_docs` sweep), also callable standalone on an existing `docs_dir` |
| **Find a node's doc** | normalized-name match → **H1-title fallback** for arbitrary names; claim files so two nodes can't take the same doc |
| **Canonical name** | sanitize **`/` and `\` → `_`** only; keep the rest of the key raw (spaces, `#`). One shared rule in Python and the nav JS |
| **Thoroughness** | rename files + nav only (no in-body markdown link rewriting) |
| **Nav** | `buildNavItem` uses the shared slug; `loadDocument` URL-encodes the fetched filename (covers `#`/spaces for nav *and* body-link clicks, which both route through it) |
| **Scope** | build + test, then run the pass on the existing wiki and regenerate `index.html` |

## 4. Detailed design

### 4.1 `canonical_doc_name(node_key) -> str`

A new module-level function (in `codewiki/src/be/documentation_generator.py`,
near `_resolve_child_docs_path`):

```python
import re
def canonical_doc_name(node_key: str) -> str:
    """The on-disk doc filename for a module-tree node: sanitize only the
    filesystem path separators, keep everything else (spaces, '#') raw."""
    return re.sub(r"[\\/]", "_", node_key) + ".md"
```

Its **JS twin** (the slug used in the nav) must apply the identical rule:
`key.replace(/[\\/]/g, '_') + '.md'`.

### 4.2 Canonicalization pass

A module-level function (importable without constructing a backend, so the
standalone re-normalization needs no LLM config):

```python
def canonicalize_doc_filenames(working_dir: str, module_tree: dict) -> list[tuple]:
    """Rename each node's doc to canonical_doc_name(key). Returns the list of
    (old, new) renames performed. Idempotent."""
```

Algorithm:
1. Build an index of actual docs: `{normalized(filename_without_ext): filename}`
   from `os.listdir(working_dir)` for `*.md` except `overview.md`
   (`normalized(s) = re.sub(r"[^a-z0-9]", "", s.lower())`).
2. Resolve nodes to files in **two phases** (so a stronger name match always wins
   over a weaker H1 match, regardless of tree order — this is how the validated
   investigation ran):
   - **Phase 1 — normalized-name match:** for every node with `components` (reuse
     `_iter_tree_nodes`), look up `normalized(key)` in the index; if found among
     not-yet-`claimed` files, claim it for that node.
   - **Phase 2 — H1 fallback:** for each still-unresolved node, scan the remaining
     unclaimed `*.md`, read each file's first `# ` heading, and if exactly one has
     `normalized(key)` as a substring of `normalized(h1)`, claim it. (Zero or more
     than one → leave the node unresolved + log.)
3. For each resolved (node → file) pair, if `file != canonical_doc_name(key)`,
   rename it (see collision rule).
4. **Collision rule:** if the canonical target already exists and is a *different*
   file (compare via `os.path.realpath` / inode, accounting for the
   case-insensitive mount), skip the rename and log a warning rather than
   clobber. Use the actual on-disk name as the rename source and the exact
   canonical name as the destination (so casing is corrected even on a
   case-insensitive FS, e.g. via a two-step temp rename if source and dest differ
   only by case).
5. Log a summary (renamed N, unresolved nodes, collisions).

Called at the **end of `generate_module_documentation`** (after the overview is
generated) so the standard generate path also emits canonical filenames. The
module tree itself is **not** modified — the nav derives filenames from node keys.

### 4.3 Nav changes (`viewer_template.html`)

Two small edits:
- `buildNavItem`: `const fileName = slug(key) + '.md';` where
  `function slug(k){ return k.replace(/[\\/]/g, '_'); }` (the JS twin of
  `canonical_doc_name`).
- `loadDocument(filename)`: build the fetch path with the filename URL-encoded,
  e.g. `const docPath = DOCS_BASE_PATH ? \`${DOCS_BASE_PATH}/${encodeURIComponent(filename)}\` : encodeURIComponent(filename);`
  so `#` and spaces in the (already `/`-free) filename resolve. The existing
  content click-handler that routes `.md` body links through `loadDocument` is
  unchanged, so this fixes both nav and inline links centrally.

### 4.4 Apply to the existing wiki

A short standalone invocation (stdlib + the two new functions): load
`codebase-memory-mcp/codewiki-docs/module_tree.json`, call
`canonicalize_doc_filenames`, then regenerate `index.html` via
`HTMLGenerator().generate(...)`. Snapshot the docs dir first; verify afterward
that `canonical_doc_name(key)` exists on disk for every node.

## 5. Testing

- **`canonical_doc_name`** (unit): `/` and `\` → `_`; spaces and `#` preserved;
  `.md` appended. E.g. `C# Resolver`→`C# Resolver.md`,
  `TypeScript/JavaScript Resolver`→`TypeScript_JavaScript Resolver.md`,
  `Plain`→`Plain.md`.
- **`canonicalize_doc_filenames`** (unit, temp dir): variant rename
  (`Rust_Resolver.md`→`Rust Resolver.md`); H1-fallback rename (a `cs_lsp.md` whose
  H1 names the node → `C# Resolver.md`); already-canonical → no-op; collision →
  skip + no clobber; idempotency (second run renames nothing); claiming (two nodes
  with similar keys don't grab the same file).
- **Python↔JS parity** (unit): a shared fixture list of `(key, expected_file)`;
  assert `canonical_doc_name` matches, and run the JS slug rule via `node -e`
  (Node is already a project dependency for Mermaid validation) over the same
  fixture, asserting equality — so the two implementations cannot drift.

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -p no:capture`
(`tests/` is gitignored — add new test files with `git add -f`).

## 6. Files touched

| File | Change |
|---|---|
| `codewiki/src/be/documentation_generator.py` | add `canonical_doc_name` + `canonicalize_doc_filenames`; call the pass at the end of `generate_module_documentation` |
| `codewiki/templates/github_pages/viewer_template.html` | `slug()` in `buildNavItem`; URL-encode in `loadDocument` |
| `tests/` (new test file, `git add -f`) | unit tests above |
| `codebase-memory-mcp/codewiki-docs/` (target repo) | 8 files renamed + `index.html` regenerated (Section 4.4) |

## 7. Honest limitations

- **H1 fallback is a heuristic.** If an arbitrary-named doc's H1 doesn't contain
  its node key, it stays unresolved (logged, left as-is — no worse than today). On
  the current wiki it resolves everything (0 unresolved).
- **In-body links to a `/`-named module** (e.g. `[…](TypeScript/JavaScript
  Resolver.md)`) still break: the click-handler's `[^/]*\.md` regex captures only
  the segment after the last `/`. The **nav** link for that module works (renamed
  file + slug + encoded fetch); only inline cross-links to it don't. This is the
  single residual of the "no link rewriting" scope and affects one node.
- The pass **renames files only**; it does not edit module_tree.json (the nav
  derives filenames from keys) and does not rewrite in-body link text.
