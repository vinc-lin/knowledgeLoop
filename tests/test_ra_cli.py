from repo_atlas import cli


def _seed_registry(tmp_path, monkeypatch):
    reg = tmp_path / "atlas.toml"
    reg.write_text('[[repo]]\nname="r1"\nrepo_path="/p"\nwiki_dir="/w"\n'
                   'entity_map="/w/e.json"\n')
    monkeypatch.setenv("REPO_ATLAS_REGISTRY", str(reg))
    monkeypatch.setenv("REPO_ATLAS_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("REPO_ATLAS_BASE_URL", "u")
    monkeypatch.setenv("REPO_ATLAS_API_KEY", "k")
    monkeypatch.setenv("REPO_ATLAS_EMBED_MODEL", "m")


def test_parser_index_all():
    args = cli.build_parser().parse_args(["index", "--all"])
    assert args.cmd == "index" and args.all is True


def test_index_requires_all_or_repo(tmp_path, monkeypatch, capsys):
    _seed_registry(tmp_path, monkeypatch)
    rc = cli.main(["index"])                       # neither --all nor --repo
    assert rc == 2
    assert "--all or --repo" in capsys.readouterr().out


def test_index_all_dispatches_to_indexer(tmp_path, monkeypatch):
    _seed_registry(tmp_path, monkeypatch)
    seen = {}

    async def fake_index_all(entries, store, embedder):
        seen["names"] = [e.name for e in entries]
        return {e.name: 5 for e in entries}

    monkeypatch.setattr(cli._index, "index_all", fake_index_all)
    rc = cli.main(["index", "--all"])
    assert rc == 0
    assert seen["names"] == ["r1"]


def test_index_unknown_repo_errors(tmp_path, monkeypatch, capsys):
    _seed_registry(tmp_path, monkeypatch)
    rc = cli.main(["index", "--repo", "nope"])
    assert rc == 2
    assert "no repo named" in capsys.readouterr().out
