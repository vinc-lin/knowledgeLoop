from __future__ import annotations

import re

from repo_atlas.store import Unit

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) sections by ATX headings.

    Content before the first heading is dropped (it is usually frontmatter)."""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            sections.append((m.group(2).strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return [(h, "\n".join(b).strip()) for h, b in sections]


def doc_units(text: str, *, repo: str, module: str, file: str | None,
              repo_head: str | None) -> list[Unit]:
    units = []
    for ord_, (heading, body) in enumerate(chunk_markdown(text)):
        units.append(Unit(
            repo=repo, kind="doc", name=heading, qualified_name=None, file=file,
            repo_head=repo_head, text=f"{heading}\n{body}".strip(),
            meta={"module": module, "ord": ord_}))
    return units
