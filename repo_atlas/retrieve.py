from __future__ import annotations


def rrf_fuse(ranked_lists: list[list[str]], k0: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over lists of ids (best-first)."""
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, _id in enumerate(lst):
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k0 + rank + 1)
    return sorted(scores.items(), key=lambda t: t[1], reverse=True)


def _hit(unit, score, matched_via) -> dict:
    return {
        "repo": unit.repo, "kind": unit.kind, "name": unit.name,
        "qualified_name": unit.qualified_name, "file": unit.file,
        "snippet": unit.text[:400], "score": round(score, 5), "matched_via": matched_via,
        "indexed_repo_head": unit.repo_head,
        "drill_down": {"repo": unit.repo, "qualified_name": unit.qualified_name},
    }


async def find_related_units(store, embedder, query: str, *, repos=None, kinds=None,
                             k: int = 20) -> list[dict]:
    qvec = embedder.embed([query])[0]
    kw = store.keyword_search(query, k=k * 2, repos=repos, kinds=kinds)
    vec = store.vector_search(qvec, k=k * 2, repos=repos, kinds=kinds)
    by_id = {u.uid: u for u, _ in kw}
    by_id.update({u.uid: u for u, _ in vec})
    fused = rrf_fuse([[u.uid for u, _ in kw], [u.uid for u, _ in vec]])
    kw_ids = {u.uid for u, _ in kw}
    vec_ids = {u.uid for u, _ in vec}
    hits = []
    for uid, score in fused[:k]:
        u = by_id[uid]
        via = "+".join((["keyword"] if uid in kw_ids else [])
                       + (["semantic"] if uid in vec_ids else []))
        hits.append(_hit(u, score, via))
    return hits
