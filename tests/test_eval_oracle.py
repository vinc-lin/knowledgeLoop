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
