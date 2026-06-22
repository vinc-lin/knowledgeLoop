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
                          max_chars: int = 500, doc_lines: int = 6, body_lines: int = 3) -> str:
    """Preceding doc-comment + signature (the "leaner" enrichment), from a symbol's source FILE text.

    `body_lines` defaults to 3 — just the signature region, NOT the implementation body. The eval
    (lap 6) showed including the full body (~15 lines) is net-neutral: it dilutes a strong
    name-anchored embedding as often as it helps. Doc-comment + signature is the pure behavioral
    signal and measurably lifts symbol-precise retrieval (required-API in top-10: 3/11 -> 6/11).
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
