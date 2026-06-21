from repo_atlas.retrieve import _merge_quota

S = [{"kind": "symbol", "i": i} for i in range(6)]
D = [{"kind": "doc", "i": i} for i in range(6)]


def _kinds(xs):
    return [x["kind"] for x in xs]


def test_exact_quota_interleaves_symbol_first():
    out = _merge_quota(S, D, n_sym=2, n_doc=2, k=4)
    assert _kinds(out) == ["symbol", "doc", "symbol", "doc"]


def test_backfill_when_docs_short():
    out = _merge_quota(S, D[:1], n_sym=3, n_doc=3, k=6)
    assert len(out) == 6
    assert _kinds(out).count("symbol") == 5 and _kinds(out).count("doc") == 1


def test_backfill_when_symbols_short():
    out = _merge_quota(S[:1], D, n_sym=3, n_doc=3, k=6)
    assert len(out) == 6
    assert _kinds(out).count("symbol") == 1 and _kinds(out).count("doc") == 5


def test_caps_at_k_and_handles_small_pools():
    assert _merge_quota(S[:1], D[:1], n_sym=3, n_doc=3, k=6) == [S[0], D[0]]
