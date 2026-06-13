"""Reconcile CodeWiki repo-relative paths with CBM file_path values."""

from __future__ import annotations


def normalize_path(path: str, repo_root: str | None = None) -> str:
    """Return a forward-slash, repo-relative path.

    Strips an absolute ``repo_root`` prefix when given, normalizes Windows
    separators, and removes a single leading ``./`` or ``/``.
    """
    p = path.replace("\\", "/")
    if repo_root:
        root = repo_root.replace("\\", "/").rstrip("/")
        if p.startswith(root + "/"):
            p = p[len(root) + 1:]
    if p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]
    return p


def path_suffix_match(a: str, b: str) -> bool:
    """True if the two paths share an identical trailing run of segments.

    Segment-aware so ``config.py`` does not match ``myconfig.py``.
    """
    pa = [s for s in a.split("/") if s]
    pb = [s for s in b.split("/") if s]
    if not pa or not pb:
        return False
    n = min(len(pa), len(pb))
    return pa[-n:] == pb[-n:]
