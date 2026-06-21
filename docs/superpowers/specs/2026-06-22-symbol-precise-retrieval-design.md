# Symbol-Precise Retrieval (symbol text enrichment) — Design Spec

**Date:** 2026-06-22
**Status:** Approved design, pending implementation plan
**Related:** `docs/repo-atlas-evaluation.md` (lap 5 — the grounding eval that identified this gap),
the grounding-based finding-bottleneck eval (`2026-06-21-grounded-finding-bottleneck-eval-*`).

## Why

The judge-free grounding eval (lap 5) showed repo_atlas does **not** help the agent ground in the
right *specific* API: grounded-success 20%→20%, and `find_related` surfaced the required symbol's
file only **30%** of the time. The root cause is concrete and decisive — symbols are indexed
**content-free**:

```
convert_to_clbuffer  →  text = "convert_to_clbuffer Function <qualified.path> <file>"
cgeGetBlendModeName  →  text = "cgeGetBlendModeName Function <qualified.path> <file>"
```

The indexed `text` (`repo_atlas/index.py:_symbol_unit`) is just `name + label + qualified_name +
file` — no signature, no doc comment, no body. So a *goal-phrased* query ("turn a VideoBuffer into
a CLBuffer") has nothing behavioral to match; the symbol embedding is effectively its name, and the
right symbol ranks ~20–40 (losing to classes/enums that share name tokens).

The fix needs no new retrieval algorithm: **enrich symbol representations with their actual source**
so goal-queries match what a symbol *does*. CBM rows already carry the line span, so the source is
available at index time for free.

## Decisions (locked during brainstorming)

- **Enrichment depth:** doc-comment + signature + first ~15 body lines, **capped (~500 chars)**.
  No LLM summaries (tens-of-thousands of calls/corpus) — a later upgrade if the cheap version
  underdelivers.
- **Scope:** enrich + re-index **only**, then re-measure with the grounding eval. No new tool —
  the symbols are already retrieved (just ranked low); fixing the text should fix the ranking.

## Non-goals

- No `find_symbol`/`find_api` tool, no retrieval-algorithm change, no doc-unit text change, no LLM
  summarization. (All deferred, contingent on the measured result.)

## Architecture

One indexing-side change, isolated into three small units:

### 1. `repo_atlas/symbol_source.py` (new) — pure extraction

```python
def extract_symbol_source(src: str, name: str, start_line: int, end_line: int, *,
                          max_chars: int = 500, doc_lines: int = 6, body_lines: int = 15) -> str
```
- `src` = the symbol's source FILE contents (full text). Returns: preceding contiguous doc-comment
  + signature + leading body, joined and capped to `max_chars`.
- Span selection: use `[start_line, end_line]` (1-indexed) when `start_line >= 1`; else fall back to
  `_find_def_line(lines, name)` — the first line where `name` appears with `(`/`{`/`#define`/
  `typedef` (then the first line containing `name`). End = `min(end_line or start+body_lines,
  start+body_lines, len)`.
- Doc comment: walk up from the definition line over a contiguous block of comment/`*`/blank lines
  (bounded by `doc_lines`) and prepend it.
- Pure: no IO — given the file text, fully testable.

### 2. `repo_atlas/index.py:_symbol_unit` / `build_units` — inject a source reader

- `_symbol_unit(row, *, repo, repo_head, source_reader=None)`: keep the base
  `name + label + qn + file`; if `source_reader` and `file`, append
  `extract_symbol_source(source_reader(file), name, start_line, end_line)`:
  ```python
      base = " ".join(p for p in [name, label, qn, file] if p)
      enrich = ""
      if source_reader and file:
          src = source_reader(file)
          if src:
              enrich = extract_symbol_source(src, name, int(row.get("start_line") or 0),
                                             int(row.get("end_line") or 0))
      text = base + ("\n" + enrich if enrich else "")
  ```
- `build_units(..., source_reader=None)`: thread it to `_symbol_unit`. Stays "pure given the
  reader" — tests inject a dict-backed stub reader (no real IO), so `build_units`/`_symbol_unit`
  remain unit-testable.

### 3. `repo_atlas/index.py:index_repo` — wire a repo-bound, cached reader

```python
def _make_source_reader(repo_path: str):
    cache: dict[str, str] = {}
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
`index_repo` passes `source_reader=_make_source_reader(entry.repo_path)` into `build_units`. The
per-file cache avoids re-reading a file for its many symbols.

## Measurement (the point of the whole eval program)

1. **Re-index** all 3 corpora (`repo-atlas index --all`) — enriched symbol text → new embeddings;
   one-time, local bge-m3.
2. **Primary — re-run the grounding eval** (`--scorer grounding`, the 11 finding-bottleneck tasks).
   Expect **surfaced (30%) and grounded-success (20%) to rise materially** — the direct test.
3. **Regression guard — re-run the offline eval.** Broad-query file-level Success@20 (0.80) must
   **hold**; symbol-level Success should **improve**. (Only symbol text changed; docs untouched.)
4. **Mechanism spot-check:** the symbol-only rank of `convert_to_clbuffer` / `cgeGetBlendModeName`
   for their goal queries (was 20 / 40) should climb sharply.

## Risks & open questions

- **Missing line ranges.** Some CBM rows may have `start_line = 0` for C/C++. Mitigated by the
  `_find_def_line` name-grep fallback; if even that misses, the unit just keeps its base text (no
  worse than today).
- **Cap too tight.** A 500-char cap could truncate a verbose C++ signature before the body; the cap
  is generous enough for signature + doc, and the body is a bonus. Tune if the spot-check shows
  truncation hurting.
- **Noise.** Enriched text adds tokens that could perturb *broad* doc queries — but only **symbol**
  units change (docs untouched), and the offline eval is the explicit regression guard.
- **Re-index cost / dependencies.** Re-indexing needs CBM (`uvx codebase-memory-mcp`) + the corpora
  + wiki dirs (all present in the eval setup). ~50k symbols re-embedded locally — minutes-to-an-hour,
  one-time.
- **`build_units` purity.** Reading source is IO; we preserve testability by *injecting* the reader
  (pure given the reader) rather than reading inside `build_units`.
```
