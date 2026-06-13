# Canonical Doc Filenames + Nav Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every module's doc reachable from the wiki by deterministically renaming each doc to its node-key name (sanitizing only path separators), plus a nav slug + URL-encoding fix — then apply it to the existing `codebase-memory-mcp` wiki.

**Architecture:** A module-level `canonical_doc_name(key)` (sanitize `/`,`\` → `_`) and a `canonicalize_doc_filenames(working_dir, module_tree)` pass that resolves each node to its on-disk doc (normalized-name match, then H1-title fallback) and renames it to canonical, run at the end of `generate_module_documentation` and callable standalone. The nav template (`viewer_template.html`) gets a matching JS `slug()` and a `encodeURIComponent` fetch fix.

**Tech Stack:** Python 3.12, pytest, Node 18 (already a dependency, used for a Python↔JS parity test), the static `github_pages` HTML template.

---

## Reference: current code

- `codewiki/src/be/documentation_generator.py`
  - module imports (lines 1–7): `asyncio, logging, os, json, typing, copy, traceback` — **`re` is NOT imported**.
  - `_resolve_child_docs_path` (static, ~line 129), `_iter_tree_nodes` (~line 158).
  - `generate_module_documentation` returns `return working_dir` at **line 386** (common to the clustered and whole-repo branches). `module_tree_path` and `working_dir` are in scope there. `OVERVIEW_FILENAME` and `MODULE_TREE_FILENAME` are already imported (used at lines 379/384).
  - `file_manager.load_json` / `save_json` are available.
- `codewiki/templates/github_pages/viewer_template.html`
  - `buildNavItem` (line 468): `const fileName = \`${key}.md\`;`
  - `formatNavTitle` (line 494) — good neighbor to add a `slug()` helper.
  - `loadDocument` (line 502): builds `docPath` (line 510): `const docPath = DOCS_BASE_PATH ? \`${DOCS_BASE_PATH}/${filename}\` : filename;` then `fetch(docPath)`.
  - A content click-handler (lines ~554–585) already routes `.md` body links through `loadDocument` — no change needed there.

`tests/` is gitignored — stage new test files with `git add -f`. Run pytest with `-p no:cacheprovider --no-cov -p no:capture` (pyproject sets `--cov`; `-p no:capture` avoids a pre-existing WSL2 teardown quirk).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `codewiki/src/be/documentation_generator.py` | doc generation + resolution | add `import re`; add `canonical_doc_name`, `canonicalize_doc_filenames` (+ helpers `_norm_name`, `_first_h1`); call the pass before `return working_dir` |
| `codewiki/templates/github_pages/viewer_template.html` | wiki nav/loader | add `slug()`; use it in `buildNavItem`; URL-encode in `loadDocument` |
| `tests/test_canonical_doc_filenames.py` | tests | new file (`git add -f`) |
| `codebase-memory-mcp/codewiki-docs/` (target repo) | wiki output | 8 renames + `index.html` regenerated (Task 5) |

---

## Task 1: `canonical_doc_name`

**Files:**
- Modify: `codewiki/src/be/documentation_generator.py` (add `import re`; add the function)
- Test: `tests/test_canonical_doc_filenames.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_canonical_doc_filenames.py`:

```python
"""Canonical doc filenames + the canonicalization pass."""

from codewiki.src.be.documentation_generator import canonical_doc_name


def test_canonical_plain_name():
    assert canonical_doc_name("Core Infrastructure") == "Core Infrastructure.md"


def test_canonical_keeps_hash():
    assert canonical_doc_name("C# Resolver") == "C# Resolver.md"


def test_canonical_sanitizes_forward_slash():
    assert canonical_doc_name("TypeScript/JavaScript Resolver") == "TypeScript_JavaScript Resolver.md"


def test_canonical_sanitizes_backslash():
    assert canonical_doc_name("A\\B") == "A_B.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_filenames.py -p no:cacheprovider --no-cov -p no:capture -q`
Expected: FAIL — `ImportError: cannot import name 'canonical_doc_name'`.

- [ ] **Step 3: Implement**

In `codewiki/src/be/documentation_generator.py`, add `import re` to the top imports (after `import json`), then add this module-level function (place it near the top of the module, after the imports and before the class):

```python
def canonical_doc_name(node_key: str) -> str:
    """The on-disk doc filename for a module-tree node.

    Sanitize only the filesystem path separators (``/`` and ``\\``); keep the
    rest of the key raw (spaces, ``#``). This is the contract the wiki nav uses
    (its JS ``slug()`` applies the identical rule).
    """
    return re.sub(r"[\\/]", "_", node_key) + ".md"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_filenames.py -p no:cacheprovider --no-cov -p no:capture -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add codewiki/src/be/documentation_generator.py
git add -f tests/test_canonical_doc_filenames.py
git commit -m "feat(docs): add canonical_doc_name (sanitize path separators only)"
```

---

## Task 2: `canonicalize_doc_filenames` pass

**Files:**
- Modify: `codewiki/src/be/documentation_generator.py` (add helpers + the pass)
- Test: `tests/test_canonical_doc_filenames.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_canonical_doc_filenames.py`:

```python
import os

from codewiki.src.be.documentation_generator import canonicalize_doc_filenames


def _write(d, name, body="# Doc\n"):
    with open(os.path.join(str(d), name), "w", encoding="utf-8") as fh:
        fh.write(body)


def test_pass_renames_variant_name(tmp_path):
    _write(tmp_path, "Rust_Resolver.md")
    tree = {"Rust Resolver": {"components": ["a::A"], "children": {}}}
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    assert renames == [("Rust_Resolver.md", "Rust Resolver.md")]
    assert os.path.exists(os.path.join(str(tmp_path), "Rust Resolver.md"))


def test_pass_h1_fallback_for_arbitrary_name(tmp_path):
    _write(tmp_path, "cs_lsp.md", "# C# Resolver (cs_lsp)\n\nbody\n")
    tree = {"C# Resolver": {"components": ["a::A"], "children": {}}}
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    assert renames == [("cs_lsp.md", "C# Resolver.md")]
    assert os.path.exists(os.path.join(str(tmp_path), "C# Resolver.md"))


def test_pass_noop_when_already_canonical(tmp_path):
    _write(tmp_path, "Core Infrastructure.md")
    tree = {"Core Infrastructure": {"components": ["a::A"], "children": {}}}
    assert canonicalize_doc_filenames(str(tmp_path), tree) == []
    assert os.path.exists(os.path.join(str(tmp_path), "Core Infrastructure.md"))


def test_pass_is_idempotent(tmp_path):
    _write(tmp_path, "Rust_Resolver.md")
    tree = {"Rust Resolver": {"components": ["a::A"], "children": {}}}
    canonicalize_doc_filenames(str(tmp_path), tree)
    assert canonicalize_doc_filenames(str(tmp_path), tree) == []


def test_pass_skips_collision_without_clobber(tmp_path):
    # Two nodes whose canonical names collide ("A/B" and "A_B" -> "A_B.md").
    _write(tmp_path, "A_B.md", "# A_B\n\noriginal A_B\n")        # already canonical for node "A_B"
    _write(tmp_path, "ab_doc.md", "# A/B\n\nnode A/B\n")          # node "A/B" doc, H1 names it
    tree = {
        "A_B": {"components": ["a::A"], "children": {}},
        "A/B": {"components": ["b::B"], "children": {}},
    }
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    # "A_B.md" stays as-is (already canonical); "ab_doc.md" cannot become "A_B.md" (collision) -> skipped
    assert ("ab_doc.md", "A_B.md") not in renames
    assert os.path.exists(os.path.join(str(tmp_path), "ab_doc.md"))
    with open(os.path.join(str(tmp_path), "A_B.md"), encoding="utf-8") as fh:
        assert "original A_B" in fh.read()


def test_pass_recurses_into_children(tmp_path):
    _write(tmp_path, "child_doc.md", "# Child Mod\n")
    tree = {"Parent": {"components": ["p::P"], "children": {
        "Child Mod": {"components": ["c::C"], "children": {}}}}}
    # "Parent" has no matching file (left unresolved, logged); child resolves via name
    renames = canonicalize_doc_filenames(str(tmp_path), tree)
    assert ("child_doc.md", "Child Mod.md") in renames
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_filenames.py -k pass_ -p no:cacheprovider --no-cov -p no:capture -q`
Expected: FAIL — `ImportError: cannot import name 'canonicalize_doc_filenames'`.

- [ ] **Step 3: Implement**

In `codewiki/src/be/documentation_generator.py`, add these module-level helpers and the pass (next to `canonical_doc_name`):

```python
def _norm_name(s: str) -> str:
    """Casefold + drop non-alphanumerics, for matching keys to filenames."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _first_h1(path: str) -> str:
    """Return the text of the first markdown ``# `` heading, or ''."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return ""


def canonicalize_doc_filenames(working_dir: str, module_tree: dict) -> list:
    """Rename each module-tree node's doc to ``canonical_doc_name(key)``.

    Resolution is two-phase so a normalized-name match always beats a weaker
    H1-title match regardless of tree order. Renames files only (the nav derives
    filenames from node keys, so the tree is untouched). Idempotent. Returns the
    list of ``(old_name, new_name)`` renames performed.
    """
    keys = []

    def _walk(t):
        for name, info in t.items():
            if not isinstance(info, dict):
                continue
            if info.get("components"):
                keys.append(name)
            _walk(info.get("children") or {})

    _walk(module_tree)

    md_files = [f for f in os.listdir(working_dir)
                if f.endswith(".md") and f != OVERVIEW_FILENAME]
    by_norm = {}
    for f in md_files:
        by_norm.setdefault(_norm_name(f[:-3]), []).append(f)

    claimed = set()
    resolved = {}

    # Phase 1: normalized-name match.
    for key in keys:
        if key in resolved:
            continue
        for f in by_norm.get(_norm_name(key), []):
            if f not in claimed:
                resolved[key] = f
                claimed.add(f)
                break

    # Phase 2: H1-title fallback for still-unresolved nodes.
    for key in keys:
        if key in resolved:
            continue
        nk = _norm_name(key)
        if not nk:
            continue
        matches = [f for f in md_files
                   if f not in claimed and nk in _norm_name(_first_h1(os.path.join(working_dir, f)))]
        if len(matches) == 1:
            resolved[key] = matches[0]
            claimed.add(matches[0])
        else:
            logger.warning("canonicalize: unresolved node %r (candidates=%s)", key, matches)

    renames = []
    for key, f in resolved.items():
        target = canonical_doc_name(key)
        if f == target:
            continue
        src = os.path.join(working_dir, f)
        dst = os.path.join(working_dir, target)
        if os.path.exists(dst) and not os.path.samefile(src, dst):
            logger.warning("canonicalize: target %r exists (different file); skipping %r", target, f)
            continue
        if os.path.exists(dst) and os.path.samefile(src, dst):
            # case/separator-only difference on a case-insensitive FS: two-step rename.
            tmp = src + ".tmprename"
            os.rename(src, tmp)
            os.rename(tmp, dst)
        else:
            os.rename(src, dst)
        renames.append((f, target))
        logger.info("canonicalize: %s -> %s", f, target)
    return renames
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_filenames.py -p no:cacheprovider --no-cov -p no:capture -q`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add codewiki/src/be/documentation_generator.py
git add -f tests/test_canonical_doc_filenames.py
git commit -m "feat(docs): add canonicalize_doc_filenames pass (name + H1 resolution)"
```

---

## Task 3: Wire the pass into generation

**Files:**
- Modify: `codewiki/src/be/documentation_generator.py` (`generate_module_documentation`, before `return working_dir` at line ~386)

This is wiring; the pass itself is unit-tested in Task 2. No new unit test (driving the full `generate_module_documentation` requires an LLM); verification is the call's presence + the full suite.

- [ ] **Step 1: Add the call**

In `generate_module_documentation`, immediately before `return working_dir` (the single return at the end of the method, ~line 386), insert:

```python
        # Canonicalize doc filenames to the nav's ${node-key}.md contract.
        canonicalize_doc_filenames(working_dir, file_manager.load_json(module_tree_path))

        return working_dir
```

- [ ] **Step 2: Verify the call is present and well-formed**

Run: `cd /mnt/x/code/knowledgeLoop && grep -n "canonicalize_doc_filenames(working_dir" codewiki/src/be/documentation_generator.py`
Expected: two matches — the function definition and this new call site.

- [ ] **Step 3: Run the full suite (no regressions)**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -p no:capture -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add codewiki/src/be/documentation_generator.py
git commit -m "feat(docs): canonicalize doc filenames at end of generation"
```

---

## Task 4: Nav template slug + URL-encoding (+ Python↔JS parity)

**Files:**
- Modify: `codewiki/templates/github_pages/viewer_template.html`
- Test: `tests/test_canonical_doc_filenames.py`

- [ ] **Step 1: Write the failing tests**

Append the test code below, then **consolidate all imports for the file to the top** (move the `import os` / `from ...documentation_generator import canonicalize_doc_filenames` added in Task 2, plus the new `import json`, `import re`, `import subprocess`, and the `TEMPLATE` constant, into the import block at the top alongside Task 1's `from ...documentation_generator import canonical_doc_name`). The final top block should be: `import json`, `import os`, `import re`, `import subprocess`, then `from codewiki.src.be.documentation_generator import canonical_doc_name, canonicalize_doc_filenames`, then `TEMPLATE = "codewiki/templates/github_pages/viewer_template.html"`. Append to `tests/test_canonical_doc_filenames.py`:

```python
# (TEMPLATE constant goes in the consolidated top block; shown here for context)
TEMPLATE = "codewiki/templates/github_pages/viewer_template.html"


def test_template_defines_slug_and_encodes():
    tmpl = open(TEMPLATE, encoding="utf-8").read()
    assert "function slug(" in tmpl, "slug() helper missing from template"
    assert "slug(key)" in tmpl, "buildNavItem should use slug(key)"
    assert "encodeURIComponent(" in tmpl, "loadDocument should URL-encode the filename"


def test_python_js_slug_parity():
    """Extract the template's slug() and run it via node; it must equal canonical_doc_name."""
    tmpl = open(TEMPLATE, encoding="utf-8").read()
    m = re.search(r"function slug\((\w+)\)\s*\{(.*?)\}", tmpl, re.DOTALL)
    assert m, "could not locate function slug(...) in template"
    arg, body = m.group(1), m.group(2).strip()
    keys = ["Plain", "C# Resolver", "TypeScript/JavaScript Resolver", "A\\B", "Rust Resolver"]
    js = (f"const slug=({arg})=>{{{body}}};"
          "const keys=JSON.parse(process.argv[1]);"
          "console.log(JSON.stringify(keys.map(slug)));")
    out = subprocess.run(["node", "-e", js, json.dumps(keys)],
                         capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [canonical_doc_name(k) for k in keys]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_filenames.py -k "slug or parity or encodes" -p no:cacheprovider --no-cov -p no:capture -q`
Expected: FAIL — `function slug(` not yet in the template.

- [ ] **Step 3: Edit the template**

In `codewiki/templates/github_pages/viewer_template.html`:

(a) Add a `slug` helper just above `function formatNavTitle(key) {` (~line 494). It must return the full filename so it equals `canonical_doc_name`:

```javascript
        function slug(key) { return key.replace(/[\/\\]/g, '_') + '.md'; }

```

(b) In `buildNavItem`, change line 468 from:

```javascript
            const fileName = `${key}.md`;
```
to:
```javascript
            const fileName = slug(key);
```

(c) In `loadDocument`, change the `docPath` line (~510) from:

```javascript
                const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${filename}` : filename;
```
to:
```javascript
                const docPath = DOCS_BASE_PATH ? `${DOCS_BASE_PATH}/${encodeURIComponent(filename)}` : encodeURIComponent(filename);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_canonical_doc_filenames.py -p no:cacheprovider --no-cov -p no:capture -q`
Expected: PASS (entire file, including parity via node).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -p no:capture -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add codewiki/templates/github_pages/viewer_template.html
git add -f tests/test_canonical_doc_filenames.py
git commit -m "feat(wiki): nav uses canonical slug + URL-encodes doc fetch"
```

---

## Task 5: Apply to the existing `codebase-memory-mcp` wiki

Operational (no new unit tests). Renames the 8 mismatched docs and regenerates `index.html`.

**Files:**
- Output: `/mnt/x/code/codebase-memory-mcp/codewiki-docs/` (8 renames + `index.html`)

- [ ] **Step 1: Snapshot (safety)**

```bash
cd /mnt/x/code/codebase-memory-mcp/codewiki-docs
mkdir -p .pretask_canon && cp *.md module_tree.json index.html .pretask_canon/ 2>/dev/null
ls *.md | wc -l   # expect 70
```

- [ ] **Step 2: Run the canonicalization pass + regenerate index.html**

```bash
cd /mnt/x/code/knowledgeLoop
CODEWIKI_NO_KEYRING=1 .venv/bin/python - <<'PY'
import json
from pathlib import Path
from codewiki.src.be.documentation_generator import canonicalize_doc_filenames
from codewiki.cli.html_generator import HTMLGenerator

REPO = Path("/mnt/x/code/codebase-memory-mcp")
DOCS = REPO / "codewiki-docs"
tree = json.load(open(DOCS / "module_tree.json"))
renames = canonicalize_doc_filenames(str(DOCS), tree)
print(f"renamed {len(renames)} files:")
for old, new in renames:
    print(f"  {old}  ->  {new}")
g = HTMLGenerator()
info = g.detect_repository_info(REPO)
g.generate(output_path=DOCS / "index.html", title=info["name"],
           repository_url=info["url"], github_pages_url=info["github_pages_url"], docs_dir=DOCS)
print("index.html regenerated")
PY
```
Expected: 8 renames (`go_resolver.md`→`Go Resolver.md`, `Java_Resolver.md`→`Java Resolver.md`, `Kotlin_Resolver.md`→`Kotlin Resolver.md`, `PHP_Resolver.md`→`PHP Resolver.md`, `Rust_Resolver.md`→`Rust Resolver.md`, `proc_macro_synthesis.md`→`Proc Macro Synthesis.md`, `cs_lsp.md`→`C# Resolver.md`, `ts_lsp.md`→`TypeScript_JavaScript Resolver.md`).

- [ ] **Step 3: Verify every node's canonical doc now exists**

```bash
cd /mnt/x/code/codebase-memory-mcp/codewiki-docs
CODEWIKI_NO_KEYRING=1 /mnt/x/code/knowledgeLoop/.venv/bin/python - <<'PY'
import json, os
from codewiki.src.be.documentation_generator import canonical_doc_name
tree = json.load(open("module_tree.json"))
def walk(t):
    for k, v in t.items():
        if v.get("components"):
            yield k
        yield from walk(v.get("children") or {})
missing = [k for k in walk(tree) if not os.path.exists(canonical_doc_name(k))]
print("MISSING canonical docs:", missing or "NONE — every node maps to an on-disk file")
PY
```
Expected: `NONE — every node maps to an on-disk file`.

- [ ] **Step 4: Sanity-check the nav references the canonical names**

```bash
cd /mnt/x/code/codebase-memory-mcp/codewiki-docs
grep -c '"C# Resolver"' index.html   # node key present in embedded tree
ls "C# Resolver.md" "Rust Resolver.md" "TypeScript_JavaScript Resolver.md" >/dev/null && echo "canonical docs on disk OK"
```
Expected: the node key appears; the canonical files exist. (No commit in `knowledgeLoop` for this step — the target repo's `codewiki-docs/` is untracked there. Remove `.pretask_canon/` once satisfied.)

---

## Self-Review notes (for the implementer)

- The two-phase resolution is deliberate: do **all** normalized-name matches first, then H1-fallback the remainder, so a node never H1-grabs a file another node would name-match.
- `os.path.samefile` is used to distinguish a genuine collision (different file at the canonical name → skip) from a case/separator-only rename on the case-insensitive `/mnt/x` mount (same file → two-step rename). Unit tests run on case-sensitive `/tmp`, where the plain rename path is exercised.
- The parity test extracts the **actual** `slug()` body from the template and runs it under Node, so the Python and JS rules cannot silently drift.
- Acceptance for the whole plan: new tests pass, full suite green, and every node in the `codebase-memory-mcp` tree resolves to an on-disk canonical doc with a regenerated `index.html`.
