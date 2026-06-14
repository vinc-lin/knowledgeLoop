"""Minimal substring search over generated wiki docs (MVP — no ranking model)."""

from __future__ import annotations


class WikiIndex:
    def __init__(self, wiki):
        self._docs = wiki.docs

    def search(self, query: str, limit: int = 10) -> list[dict]:
        q = query.lower().strip()
        hits: list[dict] = []
        if not q:
            return hits
        for name, text in self._docs.items():
            idx = text.lower().find(q)
            if idx != -1:
                start = max(0, idx - 60)
                snippet = text[start:idx + len(q) + 60].replace("\n", " ").strip()
                hits.append({"doc": name, "snippet": snippet})
            if len(hits) >= limit:
                break
        return hits
