# Body-link consistency: fix double-encode + canonicalize link targets

- **Date:** 2026-06-14
- **Status:** Approved (design) — pending implementation plan
- **Author:** vinc (with Claude)

## 1. Problem

The merged "canonical doc filenames" feature made the wiki **nav** fully
click-through, but **in-doc cross-reference links** are still broken — discovered
during browser verification. Two independent defects:

1. **Double-encode bug (code).** A rendered markdown link's `href` is
   percent-encoded by marked.js (`[x](<C# Resolver.md>)` → `href="C#%20Resolver.md"`).
   The wiki's `loadDocument` then does `encodeURIComponent(filename)` *again*
   (`viewer_template.html:512`), producing `C%23%2520Resolver.md` → **404**.
   Verified in-browser: `encodeURIComponent("C#%20Resolver.md")` → 404, whereas
   `encodeURIComponent(decodeURIComponent("C#%20Resolver.md"))` → `C%23%20Resolver.md`
   → **200**. The nav is unaffected because it passes the raw `data-file` straight
   to `loadDocument`; only the body-link path (marked → click handler →
   `loadDocument`) double-encodes. So body links to **any space/`#`-named** canonical
   doc (C# Resolver, Rust Resolver, …) cannot work without a code fix.

2. **Wrong link targets (content).** The doc-writing agent emits cross-reference
   hrefs that don't match the canonical filenames — e.g. `](cs_lsp.md)`,
   `](Rust_Resolver.md)`, `](Core_Infrastructure.md)`, `](Cargo%20Manifest%20Parser.md)`.
   On `codebase-memory-mcp` (77 broken-link occurrences) these split into: ~56
   that map to a real canonical doc, and ~21 that point at never-documented source
   files/headers (`arena.md`, `go_lsp.md`, `pipeline_internal.md` …) with no doc to
   target. Future generated wikis will reproduce the same.

A markdown destination containing a raw space is **not parsed as a link** by
marked.js (renders as literal text), so the rewrite must use marked's
angle-bracket destination form `](<Name.md>)`.

## 2. Goal

Make in-doc cross-reference links resolve in the browser — for the existing
`codebase-memory-mcp` wiki **and** every future-generated wiki — by (a) fixing the
`loadDocument` double-encode and (b) rewriting resolvable body-link targets to the
canonical doc in an angle-bracket form.

## 3. Design decisions (agreed)

| Decision | Choice |
|---|---|
| **Template fix** | `loadDocument` decodes before encoding: `encodeURIComponent(decodeURIComponent(filename))` (try/catch fallback) |
| **Engine pass** | New `canonicalize_doc_links`, run **after** `canonicalize_doc_filenames` (reuses its `[(old,new)]` rename map); also standalone |
| **Link resolution** | General only: rename-map hit **or** normalized-name match against existing canonical docs. No codebase-specific knowledge in the engine |
| **Rewrite form** | Angle-bracket canonical destination `](<Canonical Name.md>)` (idempotent) |
| **Dead links** | Links with no resolvable target are **left unchanged** (render as links; graceful in-wiki error panel if clicked) |
| **This wiki's residual semantic links** | A small explicit one-time alias map passed to the same pass (e.g. `C_Sharp_Resolver`→`C# Resolver.md`, `discover`→`discovery.md`); component-file links stay dead |

## 4. Detailed design

### 4.1 Template: `loadDocument` decode-then-encode

`codewiki/templates/github_pages/viewer_template.html`, line 512 — change:

```javascript
const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${encodeURIComponent(filename)}` : encodeURIComponent(filename);
```
to encode a once-decoded filename so a pre-encoded href (from marked) and a raw
name (from the nav's `data-file`) both resolve to a single-encoded fetch URL:

```javascript
let safe = filename;
try { safe = decodeURIComponent(filename); } catch (e) { /* leave as-is */ }
const enc = encodeURIComponent(safe);
const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${enc}` : enc;
```

The content click-handler (`setupMarkdownLinks`) and its `.md` extraction regex
are unchanged — they already pass the extracted href to `loadDocument`, which now
normalizes the encoding.

### 4.2 Engine: `canonicalize_doc_links(working_dir, renames, extra_aliases=None)`

A module-level function in `codewiki/src/be/documentation_generator.py`, next to
`canonicalize_doc_filenames`.

Inputs: `working_dir`; `renames` = the `[(old_name, new_name)]` list returned by
`canonicalize_doc_filenames`; optional `extra_aliases` = `{normalized_token:
canonical_filename}` for one-off semantic fixes.

Algorithm — for every `*.md` file in `working_dir`, rewrite each intra-wiki
markdown link destination:

1. **Match** link destinations with a regex that captures a `.md` destination
   whether or not it is angle-bracketed, and that tolerates spaces and a literal
   `#` *inside the name* (e.g. `C# Resolver.md`) plus an optional `#anchor`:
   `\]\(\s*<?([^)<>]*?\.md)(#[^)>]*)?>?\s*\)`. (Group 1 = the `.md` path, group 2 =
   the optional anchor.) Skip destinations containing `://` (external links). This
   form matches `](cs_lsp.md)`, `](<C# Resolver.md>)`, the broken raw-space
   `](C# Resolver.md)`, `%20`-encoded names, and `](file.md#sec)` alike.
2. **Resolve** the intended canonical doc for the destination's basename `b`
   (after `<>`-strip + `unquote` + drop `#anchor`):
   - exact: if `b` is an existing doc → canonical = `b`;
   - rename map: if `b` equals an `old_name` → canonical = its `new_name`;
   - normalized: if `_norm_name(b[:-3])` uniquely matches one existing doc → that doc;
   - extra alias: if `_norm_name(b[:-3])` in `extra_aliases` → its value;
   - else **unresolved** → leave the link unchanged (count it).
3. **Rewrite** the destination to `<canonical>` (angle-bracketed). If the
   destination already equals `<canonical>`, no-op (idempotent). Preserve any
   `#anchor` inside the angle brackets.
4. Write the file back only if changed. Return/log counts: rewritten, already-ok,
   unresolved (with the distinct unresolved targets).

Reuses `canonical_doc_name`/`_norm_name`. Renames files (4.1 of the prior feature)
run **before** this so canonical targets exist.

### 4.3 Generation wiring

At the end of `generate_module_documentation`, replace the single canonicalize
call with the pair:

```python
renames = canonicalize_doc_filenames(working_dir, file_manager.load_json(module_tree_path))
canonicalize_doc_links(working_dir, renames)
```

(`canonicalize_doc_filenames` already returns `renames`; today its result is
discarded.)

### 4.4 Apply to the existing wiki

Standalone run on `codebase-memory-mcp/codewiki-docs`: `canonicalize_doc_filenames`
(now a no-op — files already canonical, returns `[]`) → `canonicalize_doc_links`
with a small `extra_aliases` map for this wiki's purely-semantic targets
(`csharpresolver`/`cslsp`→`C# Resolver.md`, `tsjsresolver`/`typescriptresolver`→
`TypeScript_JavaScript Resolver.md`, `discover`→`discovery.md`,
`foundationcrossplatformcompat`→`cross_platform_compat.md`,
`uiembeddedassets`→`embedded_assets.md`, `pipelineparallel`→`pipeline_parallel_pass.md`,
`workerpool`→`pipeline_worker_pool.md`, `passlspcross`/`crosslspresolution`/
`lspcrosspass`→`pipeline_cross_lsp.md`) → regenerate `index.html`. The pass also
supersedes the broken raw-space edits already on disk (they resolve to real docs →
rewritten to `](<…>)`). Component-file links (`arena.md`, etc.) remain dead.

## 5. Testing

- **Template (unit):** assert `viewer_template.html`'s `loadDocument` contains
  `decodeURIComponent`; assert (via the existing `node`-backed harness) that
  `encodeURIComponent(decodeURIComponent("C#%20Resolver.md")) === "C%23%20Resolver.md"`.
- **`canonicalize_doc_links` (unit, temp dir):** rename-map link
  (`](cs_lsp.md)`→`](<C# Resolver.md>)`); raw-space link
  (`](C# Resolver.md)`→`](<C# Resolver.md>)`); normalized variant
  (`](Core_Infrastructure.md)`→`](<Core Infrastructure.md>)`); `%20` variant;
  `extra_aliases` hit; dead link untouched; idempotency; an `#anchor` is preserved.
- **Browser verify (manual, fresh port):** the originally-reported
  `Java Resolver` → TS/JS link and a `#`-named target (C# Resolver) load (200);
  spot-check the wiki still renders.

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -p no:capture`
(`tests/` gitignored — `git add -f`).

## 6. Files touched

| File | Change |
|---|---|
| `codewiki/templates/github_pages/viewer_template.html` | `loadDocument` decode-then-encode |
| `codewiki/src/be/documentation_generator.py` | add `canonicalize_doc_links`; call it (with `renames`) after `canonicalize_doc_filenames` |
| `tests/` (new test file, `git add -f`) | unit tests above |
| `codebase-memory-mcp/codewiki-docs/` (target repo) | body links rewritten + `index.html` regenerated |

## 7. Honest limitations

- **Dead links stay dead.** Links whose target was never a documented module
  (source files/headers like `arena.md`, `pipeline_internal.md`) are left as links
  and 404 (graceful error panel) — by design (no doc to point at, don't edit prose).
- **General resolution can't read intent.** The engine pass fixes rename-map and
  normalized matches only; purely-semantic agent inventions (e.g. `C_Sharp_Resolver`
  for `C# Resolver`) need the per-wiki `extra_aliases` and won't be caught on a
  future wiki unless added — acceptable, as those are the long tail.
- **Anchors to headings** within a rewritten target are preserved syntactically but
  not validated.
