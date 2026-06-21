# Symbol-Precise Retrieval (symbol text enrichment) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich each symbol unit's indexed text with its source (doc-comment + signature + first ~15 body lines, capped), read from the CBM line-span, so goal-phrased queries match what a symbol *does* — then re-index and re-measure with the grounding eval.

**Architecture:** Per `docs/superpowers/specs/2026-06-22-symbol-precise-retrieval-design.md`. A pure extractor + an injected `source_reader` in `repo_atlas/index.py`. No retrieval-algorithm change, no new tool.

**Tech Stack:** Python 3.12 (stdlib `re`), pytest. Re-index/measure use the `/home/vinc/repo-atlas-eval-full/` setup (CBM via `uvx`, local Ollama bge-m3).

**Conventions:**
- Run tests: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest <file> -m "not integration" -p no:cacheprovider --no-cov -q`
- `tests/` is gitignored → `git add -f`. `from __future__ import annotations`; line length 100.

---

## Task 1: `extract_symbol_source` (pure)

**Files:**
- Create: `repo_atlas/symbol_source.py`
- Test: `tests/test_symbol_source.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_symbol_source.py
from repo_atlas.symbol_source import extract_symbol_source

SRC = (
    "#include <x.h>\n"                                                       # 1
    "// Convert a VideoBuffer to the CLBuffer that backs it.\n"             # 2
    "SmartPtr<CLBuffer> convert_to_clbuffer(const SmartPtr<VideoBuffer>& b) {\n"  # 3
    "    CLBuffer *clbuf = unwrap(b);\n"                                    # 4
    "    return clbuf;\n"                                                   # 5
    "}\n"                                                                   # 6
    "int other() { return 0; }\n"                                          # 7
)


def test_uses_line_span_and_prepends_doc_comment():
    out = extract_symbol_source(SRC, "convert_to_clbuffer", start_line=3, end_line=6)
    assert "Convert a VideoBuffer" in out          # doc comment captured
    assert "convert_to_clbuffer(const SmartPtr" in out  # signature captured
    assert "unwrap(b)" in out                      # leading body captured
    assert "int other()" not in out                # stops at end_line


def test_fallback_finds_definition_without_line_range():
    out = extract_symbol_source(SRC, "convert_to_clbuffer", start_line=0, end_line=0)
    assert "convert_to_clbuffer(const SmartPtr" in out


def test_caps_to_max_chars():
    out = extract_symbol_source(SRC, "convert_to_clbuffer", 3, 6, max_chars=20)
    assert len(out) <= 20


def test_missing_symbol_and_empty_src():
    assert extract_symbol_source(SRC, "nope_not_here", 0, 0) == ""
    assert extract_symbol_source("", "x", 1, 2) == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_symbol_source.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `repo_atlas/symbol_source.py`**

```python
from __future__ import annotations

import re

_DEF_HINT = ("(", "{", "#define", "typedef")
_COMMENT_PREFIX = ("//", "/*", "*", "///")


def _find_def_line(lines: list, name: str):
    """Index of the line where `name` is defined (name + a def hint), else first line containing
    name, else None."""
    pat = re.compile(r"\b" + re.escape(name) + r"\b")
    first = None
    for i, ln in enumerate(lines):
        if pat.search(ln):
            if any(h in ln for h in _DEF_HINT):
                return i
            if first is None:
                first = i
    return first


def extract_symbol_source(src: str, name: str, start_line: int, end_line: int, *,
                          max_chars: int = 500, doc_lines: int = 6, body_lines: int = 15) -> str:
    """Preceding doc-comment + signature + leading body for a symbol, from its source FILE text.
    Uses [start_line, end_line] (1-indexed) when usable; else greps for the definition. Capped."""
    if not src or not name:
        return ""
    lines = src.splitlines()
    n = len(lines)
    if start_line and 1 <= start_line <= n:
        si = start_line - 1
    else:
        si = _find_def_line(lines, name)
    if si is None or not (0 <= si < n):
        return ""
    ei = end_line if (end_line and end_line > start_line) else (si + 1 + body_lines)
    ei = min(ei, si + 1 + body_lines, n)
    # walk up over a contiguous doc-comment block immediately above the definition
    ds = si
    j = si - 1
    while j >= 0 and (si - j) <= doc_lines:
        s = lines[j].strip()
        if s.startswith(_COMMENT_PREFIX) or s.endswith("*/"):
            ds = j
            j -= 1
        else:
            break
    return "\n".join(lines[ds:ei]).strip()[:max_chars]
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_symbol_source.py -p no:cacheprovider --no-cov -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/symbol_source.py
git add repo_atlas/symbol_source.py
git add -f tests/test_symbol_source.py
git commit -m "feat(repo_atlas): extract_symbol_source — doc-comment + signature + leading body from a file span"
```

---

## Task 2: Enrich symbol text in the indexer

**Files:**
- Modify: `repo_atlas/index.py` (`_symbol_unit`, `build_units`, `index_repo` + `_make_source_reader`)
- Test: `tests/test_ra_index.py`

- [ ] **Step 1: Write the failing tests (append to `tests/test_ra_index.py`)**

```python
def test_build_units_enriches_symbol_text_via_reader():
    from repo_atlas.index import build_units
    rows = [{"name": "convert_to_clbuffer", "qualified_name": "ns.convert_to_clbuffer",
             "label": "Function", "file_path": "a.cpp", "start_line": 2, "end_line": 4}]
    src = {"a.cpp": ("// Convert a VideoBuffer to a CLBuffer.\n"
                     "SmartPtr<CLBuffer> convert_to_clbuffer(const SmartPtr<VideoBuffer>& b) {\n"
                     "    return unwrap(b);\n}\n")}
    units = build_units(_Wiki(), rows, repo="r", repo_head="H",
                        source_reader=lambda f: src.get(f, ""))
    sym = [u for u in units if u.kind == "symbol"][0]
    assert "convert_to_clbuffer" in sym.text           # name still present
    assert "Convert a VideoBuffer" in sym.text         # enriched with the doc comment
    assert "SmartPtr<CLBuffer>" in sym.text             # enriched with the signature


def test_build_units_without_reader_is_back_compat():
    from repo_atlas.index import build_units
    rows = [{"name": "foo", "qualified_name": "foo", "label": "Function", "file_path": "a.cpp"}]
    units = build_units(_Wiki(), rows, repo="r", repo_head="H")
    assert [u for u in units if u.kind == "symbol"][0].text == "foo Function foo a.cpp"
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_index.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `build_units() got an unexpected keyword argument 'source_reader'`.

- [ ] **Step 3: Implement in `repo_atlas/index.py`**

Add the import at the top:
```python
from repo_atlas.symbol_source import extract_symbol_source
```

Replace `_symbol_unit` with a reader-aware version:
```python
def _symbol_unit(row: dict, *, repo: str, repo_head: Optional[str], source_reader=None) -> Unit:
    name = row.get("name", "")
    qn = row.get("qualified_name") or name
    label = row.get("label", "")
    file = row.get("file_path") or row.get("file")
    text = " ".join(p for p in [name, label, qn, file] if p)
    if source_reader and file:
        src = source_reader(file)
        if src:
            enrich = extract_symbol_source(src, name, int(row.get("start_line") or 0),
                                           int(row.get("end_line") or 0))
            if enrich:
                text = text + "\n" + enrich
    return Unit(repo=repo, kind="symbol", name=name, qualified_name=qn, file=file,
                repo_head=repo_head, text=text, meta={"label": label})
```

Thread `source_reader` through `build_units`:
```python
def build_units(wiki, symbol_rows: list[dict], *, repo: str,
                repo_head: Optional[str], source_reader=None) -> list[Unit]:
    """Pure given the source_reader: wiki + symbol rows -> Units. Tested directly."""
    units: list[Unit] = []
    docs = getattr(wiki, "docs", {}) or {}
    for fname, text in docs.items():
        module = fname.rsplit(".", 1)[0]
        units += doc_units(text, repo=repo, module=module, file=fname, repo_head=repo_head)
    for row in symbol_rows:
        units.append(_symbol_unit(row, repo=repo, repo_head=repo_head, source_reader=source_reader))
    return units
```

Add a cached reader factory (above `index_repo`):
```python
def _make_source_reader(repo_path: str):
    """A repo-relative file reader with a per-file cache (many symbols share a file)."""
    cache: dict = {}
    def read(rel: str) -> str:
        if rel not in cache:
            try:
                with open(os.path.join(repo_path, rel), errors="ignore") as fh:
                    cache[rel] = fh.read()
            except OSError:
                cache[rel] = ""
        return cache[rel]
    return read
```

In `index_repo`, pass the reader into `build_units`:
```python
    units = build_units(wiki, symbol_rows, repo=entry.name, repo_head=repo_head,
                        source_reader=_make_source_reader(entry.repo_path))
```

- [ ] **Step 4: Run to verify it passes (+ existing index test)**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_index.py -p no:cacheprovider --no-cov -q`
Expected: PASS (the 2 new tests + the original `test_build_units_makes_doc_and_symbol_units`).

- [ ] **Step 5: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/index.py
git add repo_atlas/index.py
git add -f tests/test_ra_index.py
git commit -m "feat(repo_atlas): enrich symbol unit text with source (injected reader) for symbol-precise retrieval"
```

---

## Task 3: Re-index + re-measure (operational, no merge)

**Files:** none. Requires CBM (`uvx codebase-memory-mcp`) + local Ollama (bge-m3) + the
`/home/vinc/repo-atlas-eval-full/` setup (atlas.toml with the 3 repos' repo_path + wiki_dir).

- [ ] **Step 1: Re-index all 3 corpora with enriched symbol text**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
cp "$FULL/atlas.db" "$FULL/atlas.db.pre-enrich.bak"     # keep the old index for comparison
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 REPO_ATLAS_API_KEY=local \
  REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas index --all
```
Expected: `indexed <repo>: N units` for all 3 (counts ≈ the prior run). Runtime: CBM index +
~50k local embeddings → minutes-to-an-hour.

- [ ] **Step 2: Confirm symbol text is now enriched (sanity)**

```bash
FULL=/home/vinc/repo-atlas-eval-full
/home/vinc/code/knowledgeLoop/.venv/bin/python - <<'PY' 2>&1 | grep -v mem.init
import os
from repo_atlas.store import Store
st = Store(os.path.expanduser("/home/vinc/repo-atlas-eval-full/atlas.db"))
for repo, api in [("libxcam", "convert_to_clbuffer"),
                  ("android-gpuimage-plus", "cgeGetBlendModeName"),
                  ("ndk-samples", "arraysize")]:
    r = st.db.execute("SELECT length(text) tl, substr(text,1,200) t FROM units "
                      "WHERE repo=? AND name=? AND kind='symbol' LIMIT 1", (repo, api)).fetchone()
    print(f"[{repo}] {api}: textlen={r['tl']}\n   {r['t']!r}\n")
PY
```
Expected: textlen now hundreds of chars and the snippet contains the signature/comment/body — not
just `<name> Function <path>`.

- [ ] **Step 3: Spot-check the symbol-only rank improved**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 \
  REPO_ATLAS_API_KEY=local REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python - <<'PY' 2>&1 | grep -v mem.init
import asyncio, os
from repo_atlas.store import Store
from repo_atlas.embed import GatewayEmbedder
from repo_atlas.retrieve import find_related_units
st = Store(os.environ["REPO_ATLAS_DB"])
emb = GatewayEmbedder(os.environ["REPO_ATLAS_BASE_URL"], os.environ["REPO_ATLAS_API_KEY"],
                      os.environ["REPO_ATLAS_EMBED_MODEL"])
async def rank(repo, api, q):
    hits = await find_related_units(st, emb, q, repos=[repo], kinds=["symbol"], k=50)
    print(f"{api}: rank={next((i+1 for i,h in enumerate(hits) if h['name']==api), None)}")
asyncio.run(rank("libxcam", "convert_to_clbuffer",
                 "turn the incoming VideoBuffer into the CLBuffer that backs it for an OpenCL kernel argument"))
asyncio.run(rank("android-gpuimage-plus", "cgeGetBlendModeName",
                 "return the canonical lowercase string name of a blend mode enum value"))
PY
```
Expected: both ranks climb sharply vs the pre-enrich baseline (was 20 / 40).

- [ ] **Step 4: Re-run the grounding eval (primary) in the background**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas eval \
  --tasks repo_atlas/eval/tasks-grounding --scorer grounding --mcp-config $FULL/mcp.json \
  --out $FULL/grounding-scorecard-enriched.md > $FULL/grounding-enriched.log 2>&1
```
Compare `grounding-scorecard-enriched.md` to `grounding-scorecard.md`: expect **surfaced (was 30%)
and grounded-success (was 20%) to rise**. Report the deltas + the category histogram shift.

- [ ] **Step 5: Regression guard — re-run the offline eval**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 REPO_ATLAS_API_KEY=local \
  REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas eval-offline \
  --cases repo_atlas/eval/offline/cases --layer retrieval --out $FULL/offline-scorecard-enriched.md
```
Expected: broad-query file-level Success@20 holds at ≈0.80 (no regression); symbol-level Success
should improve.

- [ ] **Step 6: Report (no merge — leave for the human)**

Summarize: enriched symbol textlen, the rank spot-check, grounding-eval surfaced/grounded deltas,
and the offline-eval regression check. STOP before any `git merge`/`git push`.

---

## Self-review checklist (done while writing)

- **Spec coverage:** `extract_symbol_source` pure extractor (T1), injected-reader enrichment in the
  indexer (T2), re-index + grounding-eval primary + offline regression guard + rank spot-check (T3).
  Non-goals (new tool, LLM summaries, retrieval-algorithm change, doc-text change) excluded.
- **Back-compat:** `source_reader=None` default keeps the existing `test_build_units_makes_doc_and_symbol_units`
  passing (asserted by `test_build_units_without_reader_is_back_compat`); `build_units` stays "pure
  given the reader" so unit tests use a stub, no IO.
- **Fallback handled:** `extract_symbol_source` greps for the definition when no line range
  (`test_fallback_finds_definition_without_line_range`); returns "" (base text unchanged) when the
  symbol isn't found, so enrichment never makes a unit worse than today.
- **No placeholders:** every code + command step is complete; T3 backs up `atlas.db` before re-index
  so the pre-enrich index is kept for comparison.
```
