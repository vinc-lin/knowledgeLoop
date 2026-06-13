# Body-Link Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make in-doc cross-reference links resolve in the browser by fixing the wiki's double-encode bug and rewriting resolvable body-link targets to the canonical doc.

**Architecture:** One template fix (`loadDocument` decodes before re-encoding so a marked-rendered href isn't double-encoded) plus a new engine pass `canonicalize_doc_links` that, after filenames are canonicalized, rewrites each intra-wiki `.md` link to angle-bracket canonical form via the rename map / normalized-name match / optional aliases. Then apply to the existing `codebase-memory-mcp` wiki and regenerate `index.html`.

**Tech Stack:** Python 3.12, pytest, Node 18 (for the template encoding check), the static `github_pages` HTML template.

---

## Reference: current code

- `codewiki/src/be/documentation_generator.py`
  - module-level helpers already exist: `canonical_doc_name(key)`, `_norm_name(s)`, `_first_h1(path)`, and `canonicalize_doc_filenames(working_dir, module_tree) -> list` (returns `[(old_name, new_name)]`). `import re` and `import os` are present; `logger` is module-level; `OVERVIEW_FILENAME` is imported.
  - `generate_module_documentation` ends with (line ~502–504):
    ```python
            canonicalize_doc_filenames(working_dir, file_manager.load_json(module_tree_path))

            return working_dir
    ```
- `codewiki/templates/github_pages/viewer_template.html`
  - `loadDocument(filename)` builds the fetch URL at **line 512**:
    ```javascript
                const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${encodeURIComponent(filename)}` : encodeURIComponent(filename);
    ```
  - The nav passes the raw `data-file` (`slug(key)`) straight to `loadDocument`; the content click-handler passes marked's already-encoded href. Both flow through this line.

`tests/` is gitignored — stage new test files with `git add -f`. Run pytest with `-p no:cacheprovider --no-cov -p no:capture`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `codewiki/src/be/documentation_generator.py` | doc generation + canonicalization | add `canonicalize_doc_links`; call it (with the rename list) after `canonicalize_doc_filenames` |
| `codewiki/templates/github_pages/viewer_template.html` | wiki loader | `loadDocument` decode-then-encode |
| `tests/test_canonical_doc_links.py` | tests | new file (`git add -f`) |
| `codebase-memory-mcp/codewiki-docs/` (target repo) | wiki output | body links rewritten + `index.html` regenerated (Task 4) |

---

## Task 1: `canonicalize_doc_links` pass

**Files:**
- Modify: `codewiki/src/be/documentation_generator.py` (add the function)
- Test: `tests/test_canonical_doc_links.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_canonical_doc_links.py`:

```python
"""Body-link canonicalization pass + loadDocument template fix."""

import os

from codewiki.src.be.documentation_generator import canonicalize_doc_links


def _w(d, name, body):
    with open(os.path.join(str(d), name), "w", encoding="utf-8") as fh:
        fh.write(body)


def _read(d, name):
    with open(os.path.join(str(d), name), encoding="utf-8") as fh:
        return fh.read()


def test_rewrites_rename_map_link(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "Java Resolver.md", "See [C#](cs_lsp.md).\n")
    canonicalize_doc_links(str(tmp_path), [("cs_lsp.md", "C# Resolver.md")])
    assert "](<C# Resolver.md>)" in _read(tmp_path, "Java Resolver.md")


def test_rewrites_raw_space_link(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "Java Resolver.md", "See [C#](C# Resolver.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<C# Resolver.md>)" in _read(tmp_path, "Java Resolver.md")


def test_rewrites_normalized_variant(tmp_path):
    _w(tmp_path, "Core Infrastructure.md", "# CI\n")
    _w(tmp_path, "a.md", "See [CI](Core_Infrastructure.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<Core Infrastructure.md>)" in _read(tmp_path, "a.md")


def test_rewrites_percent_encoded(tmp_path):
    _w(tmp_path, "Cargo Manifest Parser.md", "# C\n")
    _w(tmp_path, "a.md", "See [C](Cargo%20Manifest%20Parser.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<Cargo Manifest Parser.md>)" in _read(tmp_path, "a.md")


def test_extra_aliases(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "a.md", "See [x](C_Sharp_Resolver.md).\n")
    canonicalize_doc_links(str(tmp_path), [], {"csharpresolver": "C# Resolver.md"})
    assert "](<C# Resolver.md>)" in _read(tmp_path, "a.md")


def test_dead_link_untouched(tmp_path):
    _w(tmp_path, "a.md", "See [arena](arena.md).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](arena.md)" in _read(tmp_path, "a.md")


def test_anchor_preserved(tmp_path):
    _w(tmp_path, "Core Infrastructure.md", "# CI\n")
    _w(tmp_path, "a.md", "See [s](Core_Infrastructure.md#scope).\n")
    canonicalize_doc_links(str(tmp_path), [])
    assert "](<Core Infrastructure.md#scope>)" in _read(tmp_path, "a.md")


def test_idempotent(tmp_path):
    _w(tmp_path, "C# Resolver.md", "# C#\n")
    _w(tmp_path, "a.md", "See [x](cs_lsp.md).\n")
    canonicalize_doc_links(str(tmp_path), [("cs_lsp.md", "C# Resolver.md")])
    once = _read(tmp_path, "a.md")
    canonicalize_doc_links(str(tmp_path), [])  # second pass, empty rename map
    assert _read(tmp_path, "a.md") == once
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_links.py -p no:cacheprovider --no-cov -p no:capture -q`
Expected: FAIL — `ImportError: cannot import name 'canonicalize_doc_links'`.

- [ ] **Step 3: Implement**

In `codewiki/src/be/documentation_generator.py`, add this module-level function next to `canonicalize_doc_filenames` (add `from urllib.parse import unquote` to the top imports if not already present):

```python
# Matches a markdown link destination ending in .md, with or without <> wrapping,
# tolerating spaces and a literal '#' inside the name plus an optional #anchor.
_LINK_RE = re.compile(r"\]\(\s*<?([^)<>]*?\.md)(#[^)>]*)?>?\s*\)")


def canonicalize_doc_links(working_dir: str, renames: list, extra_aliases: dict = None) -> dict:
    """Rewrite intra-wiki body-link targets to the canonical doc, in angle-bracket
    markdown form so marked.js parses spaces/'#'.

    A link's intended doc is resolved via (1) the ``renames`` map (old agent
    filename -> canonical), (2) a normalized-name match against existing docs, or
    (3) an optional ``extra_aliases`` ({normalized_token: canonical_filename}).
    Unresolvable targets (no such doc) are left unchanged. Idempotent. Returns
    ``{"rewritten": n, "unresolved": m}``.
    """
    extra_aliases = extra_aliases or {}
    docs = {f for f in os.listdir(working_dir) if f.endswith(".md")}
    by_norm = {}
    for f in docs:
        by_norm.setdefault(_norm_name(f[:-3]), []).append(f)
    rename_map = {old: new for old, new in (renames or [])}

    def _canonical_for(base):
        if base in docs:
            return base
        if base in rename_map and rename_map[base] in docs:
            return rename_map[base]
        cand = by_norm.get(_norm_name(base[:-3]))
        if cand and len(cand) == 1:
            return cand[0]
        alias = extra_aliases.get(_norm_name(base[:-3]))
        return alias if alias in docs else None

    rewritten = 0
    unresolved = set()

    for src in sorted(docs):
        path = os.path.join(working_dir, src)
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()

        def repl(m):
            nonlocal rewritten
            dest, anchor = m.group(1), m.group(2) or ""
            if "://" in dest:
                return m.group(0)
            base = os.path.basename(unquote(dest))
            canon = _canonical_for(base)
            if not canon:
                unresolved.add(base)
                return m.group(0)
            desired = f"](<{canon}{anchor}>)"
            if m.group(0) != desired:
                rewritten += 1
            return desired

        new = _LINK_RE.sub(repl, text)
        if new != text:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)

    if rewritten or unresolved:
        logger.info("canonicalize_doc_links: %d rewritten; %d unresolved targets: %s",
                    rewritten, len(unresolved), sorted(unresolved))
    return {"rewritten": rewritten, "unresolved": len(unresolved)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_links.py -p no:cacheprovider --no-cov -p no:capture -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add codewiki/src/be/documentation_generator.py
git add -f tests/test_canonical_doc_links.py
git commit -m "feat(docs): add canonicalize_doc_links body-link rewriting pass"
```

---

## Task 2: Wire the link pass into generation

**Files:**
- Modify: `codewiki/src/be/documentation_generator.py` (`generate_module_documentation`, the call site at ~line 502)

Wiring; the pass is unit-tested in Task 1. Verification is the call's presence + the full suite.

- [ ] **Step 1: Replace the call site**

In `generate_module_documentation`, change the existing single canonicalize call (before `return working_dir`) from:

```python
        canonicalize_doc_filenames(working_dir, file_manager.load_json(module_tree_path))

        return working_dir
```
to capture the rename list and run the link pass after it:

```python
        renames = canonicalize_doc_filenames(working_dir, file_manager.load_json(module_tree_path))
        canonicalize_doc_links(working_dir, renames)

        return working_dir
```

- [ ] **Step 2: Verify the wiring**

Run: `cd /mnt/x/code/knowledgeLoop && grep -n "canonicalize_doc_links(working_dir, renames)" codewiki/src/be/documentation_generator.py`
Expected: one match (the new call site). Also confirm `renames = canonicalize_doc_filenames(` appears.

- [ ] **Step 3: Run the full suite (no regressions)**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -p no:capture -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add codewiki/src/be/documentation_generator.py
git commit -m "feat(docs): canonicalize body-link targets at end of generation"
```

---

## Task 3: Template `loadDocument` decode-then-encode

**Files:**
- Modify: `codewiki/templates/github_pages/viewer_template.html` (line 512)
- Test: `tests/test_canonical_doc_links.py`

- [ ] **Step 1: Write the failing tests**

Add these imports to the **top** of `tests/test_canonical_doc_links.py` (consolidate with the existing `import os`): `import shutil`, `import subprocess`, `import pytest`, and a `TEMPLATE` path constant. The top of the file should read:

```python
"""Body-link canonicalization pass + loadDocument template fix."""

import os
import shutil
import subprocess

import pytest

from codewiki.src.be.documentation_generator import canonicalize_doc_links

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "codewiki", "templates", "github_pages", "viewer_template.html",
)
```

Then append these two tests:

```python
def test_loaddocument_decodes_before_encoding():
    tmpl = open(TEMPLATE, encoding="utf-8").read()
    assert "decodeURIComponent" in tmpl, "loadDocument must decode before re-encoding"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_decode_then_encode_resolves_special_chars():
    # marked.js renders [x](<C# Resolver.md>) as href="C#%20Resolver.md";
    # decode-then-encode must yield a single-encoded, fetchable URL.
    js = "console.log(encodeURIComponent(decodeURIComponent('C#%20Resolver.md')));"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "C%23%20Resolver.md"
```

- [ ] **Step 2: Run to verify the template test fails**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_links.py -k decodes -p no:cacheprovider --no-cov -p no:capture -q`
Expected: FAIL — `decodeURIComponent` not yet in the template.

- [ ] **Step 3: Edit the template**

In `codewiki/templates/github_pages/viewer_template.html`, replace line 512:

```javascript
                const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${encodeURIComponent(filename)}` : encodeURIComponent(filename);
```
with a decode-then-encode form (try/catch so a stray `%` can't throw):

```javascript
                let safe = filename;
                try { safe = decodeURIComponent(filename); } catch (e) { /* keep raw */ }
                const enc = encodeURIComponent(safe);
                const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${enc}` : enc;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_links.py -p no:cacheprovider --no-cov -p no:capture -q`
Expected: PASS (all 10 in the file, including the node-backed check).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -p no:capture -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add codewiki/templates/github_pages/viewer_template.html
git add -f tests/test_canonical_doc_links.py
git commit -m "fix(wiki): loadDocument decodes before encoding (no double-encode)"
```

---

## Task 4: Apply to the existing `codebase-memory-mcp` wiki

Operational (no new unit tests). Rewrites this wiki's body links (incl. superseding the earlier broken raw-space edits) and regenerates `index.html` with the fixed `loadDocument`.

**Files:**
- Output: `/mnt/x/code/codebase-memory-mcp/codewiki-docs/` (body links + `index.html`)

- [ ] **Step 1: Snapshot (safety)**

```bash
cd /mnt/x/code/codebase-memory-mcp/codewiki-docs
mkdir -p .prelinks && cp *.md index.html .prelinks/ 2>/dev/null && echo "snapshot saved (.prelinks)"
```

- [ ] **Step 2: Run the link pass (+ filename pass, a no-op) + regenerate index.html**

```bash
cd /mnt/x/code/knowledgeLoop
CODEWIKI_NO_KEYRING=1 .venv/bin/python - <<'PY'
import json
from pathlib import Path
from codewiki.src.be.documentation_generator import canonicalize_doc_filenames, canonicalize_doc_links
from codewiki.cli.html_generator import HTMLGenerator

REPO = Path("/mnt/x/code/codebase-memory-mcp"); DOCS = REPO / "codewiki-docs"
EXTRA = {
    "csharpresolver": "C# Resolver.md", "cslsp": "C# Resolver.md",
    "tsjsresolver": "TypeScript_JavaScript Resolver.md",
    "typescriptresolver": "TypeScript_JavaScript Resolver.md",
    "discover": "discovery.md",
    "foundationcrossplatformcompat": "cross_platform_compat.md",
    "uiembeddedassets": "embedded_assets.md",
    "pipelineparallel": "pipeline_parallel_pass.md",
    "workerpool": "pipeline_worker_pool.md",
    "passlspcross": "pipeline_cross_lsp.md",
    "crosslspresolution": "pipeline_cross_lsp.md",
    "lspcrosspass": "pipeline_cross_lsp.md",
}
renames = canonicalize_doc_filenames(str(DOCS), json.load(open(DOCS / "module_tree.json")))
print("filename renames (expect none):", renames)
counts = canonicalize_doc_links(str(DOCS), renames, EXTRA)
print("link pass:", counts)
g = HTMLGenerator(); info = g.detect_repository_info(REPO)
g.generate(output_path=DOCS / "index.html", title=info["name"],
           repository_url=info["url"], github_pages_url=info["github_pages_url"], docs_dir=DOCS)
print("index.html regenerated")
PY
```
Expected: `filename renames (expect none): []`; `link pass: {'rewritten': N>0, 'unresolved': M}`; index.html regenerated.

- [ ] **Step 3: Audit — only genuinely-dead links remain**

```bash
cd /mnt/x/code/codebase-memory-mcp/codewiki-docs
python3 - <<'PY'
import os, re
from urllib.parse import unquote
docs = {f for f in os.listdir(".") if f.endswith(".md")}
rx = re.compile(r"\]\(\s*<?([^)<>]*?\.md)(#[^)>]*)?>?\s*\)")
rem = {}
for src in docs:
    for m in rx.finditer(open(src, encoding="utf-8", errors="ignore").read()):
        d = m.group(1)
        if "://" in d: continue
        b = os.path.basename(unquote(d))
        if b not in docs: rem[b] = rem.get(b, 0) + 1
print("remaining unresolved targets (expected: only never-documented source files):")
for t, c in sorted(rem.items()): print(f"   {t} (x{c})")
PY
```
Expected: only the component/header targets (`arena.md`, `go_lsp.md`, `c_lsp.md`, `java_lsp.md`, `rust_lsp.md`, `helpers.md`, `cbm.md`, `lsp_node_iter.md`, `pipeline_internal.md`, `pipeline_calls.md`, `pipeline_definitions.md`, `Python_Resolver.md`) — no module docs.

- [ ] **Step 4: Verify (HTTP-level, executable; browser optional)**

Confirm the regenerated `index.html` embeds the fixed loader, the fixed body links point at canonical targets, and those canonical files are served at the URLs the fixed `loadDocument` produces:

```bash
cd /mnt/x/code/codebase-memory-mcp/codewiki-docs
# 1) the fix is embedded in the regenerated wiki
grep -c "decodeURIComponent" index.html        # expect >= 1

# 2) the originally-reported broken link is now canonical (angle-bracket)
grep -o ']\(<TypeScript_JavaScript Resolver.md>)' "Java Resolver.md" | head -1
grep -o ']\(<C# Resolver.md>)' "Java Resolver.md" | head -1

# 3) serve + curl the exact single-encoded URLs the fixed loadDocument builds
python3 -m http.server 8770 --bind 127.0.0.1 >/tmp/wiki_verify.log 2>&1 &
sleep 1
for u in "TypeScript_JavaScript%20Resolver.md" "C%23%20Resolver.md" "Rust%20Resolver.md"; do
  curl -s -o /dev/null -w "$u -> HTTP %{http_code}\n" "http://127.0.0.1:8770/$u"
done
# and the double-encoded form the OLD code produced must 404 (proving the bug is the encoding):
curl -s -o /dev/null -w "C%%23%%2520Resolver.md (old double-encode) -> HTTP %{http_code}\n" "http://127.0.0.1:8770/C%23%2520Resolver.md"
pkill -f "http.server 8770"
```
Expected: `decodeURIComponent` present; both `Java Resolver.md` greps print the angle-bracket canonical links; the three single-encoded URLs return **200**; the double-encoded URL returns **404**.

Optionally, drive it in a real browser (fresh port to dodge cache) via Playwright: open `index.html`, click **Java Resolver** → its **TypeScript/JavaScript Resolver** cross-reference, and confirm the doc renders. Remove `.prelinks` once satisfied. (No commit in `knowledgeLoop` — the target repo's `codewiki-docs/` is untracked there.)

---

## Self-Review notes (for the implementer)

- The link regex `_LINK_RE` matches bracketed and unbracketed destinations, raw spaces, a `#` inside the name (e.g. `C# Resolver.md`), and a trailing `#anchor` — it must, because Task 4 also has to fix the earlier broken raw-space edits already on disk.
- For the existing wiki the rename map is empty (files were canonicalized in a prior feature), so resolution leans on normalized-match + `EXTRA`; that is expected and covered by `test_extra_aliases`.
- Acceptance for the whole plan: new tests pass, full suite green, and in the browser every resolvable cross-reference loads (200) while only never-documented component links remain dead.
