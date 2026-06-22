from __future__ import annotations

import os
from typing import Optional

from repo_atlas.chunk import doc_units
from repo_atlas.store import Store, Unit
from repo_atlas.registry import RepoEntry
from repo_atlas.symbol_source import extract_symbol_source


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


async def index_repo(entry: RepoEntry, store: Store, embedder) -> int:
    """Index one repo end-to-end (IO: wiki load + CBM enumerate + embed + store).

    Exercised by the gated integration test, not unit tests."""
    from repo_memory.wiki.loader import load_wiki
    from repo_memory.server import _resolve_repo_head
    from repo_memory.deploy import resolve_launch_spec
    from repo_memory.graph.client import CBMClient
    from repo_memory.graph import forward
    from repo_memory.graph.nodes import enumerate_all_nodes

    repo_head = _resolve_repo_head(entry.repo_path, os.environ)
    wiki = load_wiki(entry.wiki_dir)

    spec = resolve_launch_spec(environ=os.environ)
    client = CBMClient(spec.command, env=spec.env, cwd=spec.cwd)
    symbol_rows: list[dict] = []
    try:
        await client.start()
        idx = await forward.index_repository(client, repo_path=entry.repo_path)
        project = idx.get("project") if isinstance(idx, dict) else None
        if not project:
            raise RuntimeError(
                f"CBM index_repository did not return a project id (got: {idx!r})")
        symbol_rows = await enumerate_all_nodes(client, project=project)
    finally:
        await client.aclose()

    units = build_units(wiki, symbol_rows, repo=entry.name, repo_head=repo_head,
                        source_reader=_make_source_reader(entry.repo_path))
    vecs = embedder.embed([u.text for u in units]) if units else []
    store.reindex_repo(entry.name, list(zip(units, vecs)), repo_head=repo_head)
    return len(units)


async def index_all(entries: list[RepoEntry], store: Store, embedder) -> dict:
    return {e.name: await index_repo(e, store, embedder) for e in entries}
