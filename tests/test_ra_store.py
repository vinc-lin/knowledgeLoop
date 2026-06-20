from repo_atlas.store import Store, Unit


def _u(repo, kind, name, text, qn=None, file=None):
    return Unit(repo=repo, kind=kind, name=name, qualified_name=qn, file=file,
                repo_head="HEAD1", text=text, meta={})


def test_reindex_keyword_vector_and_state(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    units = [_u("r1", "symbol", "brightness", "adjust image brightness", qn="cge.brightness",
                file="f.cpp"),
             _u("r1", "doc", "Filters", "how filters are written", file="filters.md")]
    vecs = [[1.0, 0.0], [0.0, 1.0]]
    st.reindex_repo("r1", list(zip(units, vecs)), repo_head="HEAD1")

    kw = st.keyword_search("brightness", k=5)
    assert any(u.name == "brightness" for u, _ in kw)

    vec = st.vector_search([1.0, 0.0], k=5)
    assert vec[0][0].name == "brightness"          # closest to [1,0]

    states = st.list_repo_states()
    assert states[0].repo == "r1" and states[0].unit_count == 2
    assert states[0].indexed_repo_head == "HEAD1"


def test_reindex_is_idempotent(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    u = _u("r1", "symbol", "x", "x text", qn="m.x")
    st.reindex_repo("r1", [(u, [1.0, 1.0])], repo_head="H")
    st.reindex_repo("r1", [(u, [1.0, 1.0])], repo_head="H")     # again
    assert st.list_repo_states()[0].unit_count == 1            # not doubled


def test_symbols_exist_and_nearest(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    u = _u("r1", "symbol", "cgeBrightnessAdjust", "brightness filter",
           qn="cge.cgeBrightnessAdjust")
    st.reindex_repo("r1", [(u, [1.0])], repo_head="H")
    res = st.symbols_exist("r1", ["cgeBrightnessAdjust", "cgeApplyBrightness"])
    assert res["cgeBrightnessAdjust"] is True
    assert res["cgeApplyBrightness"] is False
    near = st.nearest_symbols("r1", "cgeApplyBrightness", k=3)
    assert "cgeBrightnessAdjust" in [n.name for n in near]


def test_keyword_search_with_repo_and_kind_filter(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    units = [_u("r1", "symbol", "brightness", "adjust brightness", qn="m.b"),
             _u("r1", "doc", "Brightness Guide", "brightness docs", file="b.md"),
             _u("r2", "symbol", "brightness", "other brightness", qn="m2.b")]
    vecs = [[1.0], [1.0], [1.0]]
    # reindex per repo (reindex_repo replaces a single repo's rows)
    st.reindex_repo("r1", list(zip(units[:2], vecs[:2])), repo_head="H")
    st.reindex_repo("r2", [(units[2], vecs[2])], repo_head="H")
    hits = st.keyword_search("brightness", k=10, repos=["r1"], kinds=["symbol"])
    names_repos = {(u.repo, u.kind) for u, _ in hits}
    assert names_repos == {("r1", "symbol")}      # filtered, and DOES NOT raise
