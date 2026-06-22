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
