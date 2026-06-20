from repo_atlas.embed import StubEmbedder


def test_stub_is_deterministic_and_shaped():
    e = StubEmbedder(dim=8)
    a = e.embed(["hello world", "other"])
    assert len(a) == 2 and all(len(v) == 8 for v in a)
    assert e.embed(["hello world"])[0] == a[0]      # deterministic
