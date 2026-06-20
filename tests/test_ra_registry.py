from repo_atlas.registry import load_registry, RepoEntry, repo_freshness


def test_load_registry(tmp_path):
    toml = tmp_path / "atlas.toml"
    toml.write_text(
        '[[repo]]\nname="r1"\nrepo_path="/p/r1"\nwiki_dir="/w/r1"\n'
        'entity_map="/w/r1/entity_map.json"\n')
    entries = load_registry(str(toml))
    assert entries == [RepoEntry(name="r1", repo_path="/p/r1", wiki_dir="/w/r1",
                                 entity_map="/w/r1/entity_map.json")]


class _FakeStore:
    def __init__(self, head): self._head = head
    def list_repo_states(self):
        from repo_atlas.store import RepoState
        return [RepoState("r1", self._head, 0.0, 1)] if self._head else []


def test_repo_freshness_states():
    e = RepoEntry("r1", "/p/r1", "/w/r1", "/w/r1/em.json")
    assert repo_freshness(e, _FakeStore(None), head_fn=lambda p: "H1") == "unindexed"
    assert repo_freshness(e, _FakeStore("H1"), head_fn=lambda p: "H1") == "fresh"
    assert repo_freshness(e, _FakeStore("OLD"), head_fn=lambda p: "H1") == "stale"
