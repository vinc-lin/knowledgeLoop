from repo_atlas.eval.oracle import store_exists_fn
from repo_atlas.store import Store, Unit


def test_store_exists_fn(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    u = Unit(repo="r1", kind="symbol", name="cgeImageFilter",
             qualified_name="cge.cgeImageFilter", file="f.h", repo_head="H",
             text="filter base", meta={})
    st.reindex_repo("r1", [(u, [1.0])], repo_head="H")
    exists = store_exists_fn(st, "r1")
    assert exists("cgeImageFilter") is True
    assert exists("cgeMadeUp") is False


def test_store_exists_fn_source_fallback(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.cpp").write_text("void cgeRealThing() { /* impl */ }\n")
    st = Store(str(tmp_path / "b.db"))                    # empty store: nothing indexed
    exists = store_exists_fn(st, "r1", repo_path=str(src))
    assert exists("cgeRealThing") is True                # not indexed, but present in source
    assert exists("ns::cgeRealThing") is True            # qualified -> bared -> matched
    assert exists("cgeNope") is False                    # genuinely absent


def test_store_exists_fn_no_repo_path_is_index_only(tmp_path):
    st = Store(str(tmp_path / "c.db"))
    exists = store_exists_fn(st, "r1")                    # no fallback configured
    assert exists("cgeAnything") is False
