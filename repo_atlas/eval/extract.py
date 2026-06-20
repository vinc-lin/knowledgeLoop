from __future__ import annotations

import re

_FILE = re.compile(r"^\+\+\+ b/(.+)$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# Language keywords / primitives across the corpus languages (C/C++/Java/Kotlin/
# JS/Python) — filtered so the hallucination/reuse metrics count real symbol
# references, not language noise.
_KEYWORDS = frozenset("""
if else for while do switch case break continue return goto default try catch
finally throw throws class struct enum union interface namespace template typename
typedef using public private protected internal static const final mutable volatile
register extern inline virtual override abstract sealed friend operator new delete
this self super sizeof typeof instanceof void bool boolean char byte short int long
float double unsigned signed string str auto var val let const function func def fun
lambda yield await async import from package as is in not and or xor true false null
nullptr none undefined nan with pass raise assert global nonlocal del elif print
""".split())


def _is_symbol_ref(tok: str, nextch: str) -> bool:
    """Heuristic: does this identifier look like a real symbol/API reference?

    Keeps call sites (`name(`), CamelCase, and snake_case; drops keywords and plain
    lowercase locals/words. Approximate by design — but far less noisy than counting
    every identifier, which made hallucination/reuse dominated by language tokens."""
    if tok.lower() in _KEYWORDS:
        return False
    if nextch == "(":                                      # call site
        return True
    has_upper = any(c.isupper() for c in tok)
    has_lower = any(c.islower() for c in tok)
    if has_upper and has_lower:                            # CamelCase / PascalCase
        return True
    if "_" in tok and any(c.isalpha() for c in tok):       # snake_case / JNI_OnLoad
        return True
    return False


def extract_refs(diff: str) -> tuple[list[str], list[str]]:
    """From a unified diff: (referenced symbol-like identifiers in added lines, touched files).

    Order-preserving dedup for both. See `_is_symbol_ref` for what counts as a symbol."""
    files: dict[str, None] = {}
    symbols: dict[str, None] = {}
    for line in diff.splitlines():
        fm = _FILE.match(line)
        if fm:
            files[fm.group(1).strip()] = None
            continue
        if line.startswith("+") and not line.startswith("+++"):
            body = line[1:]
            for m in _IDENT.finditer(body):
                nxt = body[m.end():m.end() + 1]
                if _is_symbol_ref(m.group(), nxt):
                    symbols[m.group()] = None
    return list(symbols), list(files)
