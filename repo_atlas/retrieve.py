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


async def _retrieve_mixed(store, embedder, query, repos, kinds, k) -> list:
    """Today's keyword+vector RRF over a (possibly kind-filtered) pool."""
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


def _merge_quota(sym_hits, doc_hits, n_sym, n_doc, k):
    """Take n_sym symbols + n_doc docs, backfilling unused slots from the other kind, then
    interleave symbol-first so both kinds appear at the top. Caps at k."""
    take_sym = sym_hits[:n_sym]
    take_doc = doc_hits[:n_doc]
    if len(take_doc) < n_doc:                      # docs short -> give slots to symbols
        take_sym = sym_hits[:n_sym + (n_doc - len(take_doc))]
    if len(take_sym) < n_sym:                      # symbols short -> give slots to docs
        take_doc = doc_hits[:n_doc + (n_sym - len(take_sym))]
    merged, i, j = [], 0, 0
    while len(merged) < k and (i < len(take_sym) or j < len(take_doc)):
        if i < len(take_sym):
            merged.append(take_sym[i])
            i += 1
        if len(merged) < k and j < len(take_doc):
            merged.append(take_doc[j])
            j += 1
    return merged[:k]


async def find_related_units(store, embedder, query, *, repos=None, kinds=None, k: int = 20,
                             symbol_ratio: float = 0.5) -> list:
    if kinds is not None:                          # explicit caller -> unchanged behavior
        return await _retrieve_mixed(store, embedder, query, repos, kinds, k)
    n_sym = k - int(k * (1.0 - symbol_ratio))      # symbols get the extra slot on odd k
    n_doc = k - n_sym
    sym = await _retrieve_mixed(store, embedder, query, repos, ["symbol"], k)
    doc = await _retrieve_mixed(store, embedder, query, repos, ["doc"], k)
    return _merge_quota(sym, doc, n_sym, n_doc, k)
