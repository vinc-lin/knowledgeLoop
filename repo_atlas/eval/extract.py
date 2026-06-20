from __future__ import annotations

import re

_FILE = re.compile(r"^\+\+\+ b/(.+)$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def extract_refs(diff: str) -> tuple[list[str], list[str]]:
    """From a unified diff: (referenced identifiers in added lines, touched files).

    Heuristic — added-line identifiers approximate the symbols/APIs the agent used."""
    files: list[str] = []
    symbols: dict[str, None] = {}
    for line in diff.splitlines():
        fm = _FILE.match(line)
        if fm:
            files.append(fm.group(1).strip())
            continue
        if line.startswith("+") and not line.startswith("+++"):
            for tok in _IDENT.findall(line[1:]):
                symbols[tok] = None
    return list(symbols), files
