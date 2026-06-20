from repo_atlas.server import build_app, TOOL_NAMES


def test_build_app_registers_tools(tmp_path, monkeypatch):
    reg = tmp_path / "atlas.toml"
    reg.write_text('[[repo]]\nname="r1"\nrepo_path="/p"\nwiki_dir="/w"\nentity_map="/w/e.json"\n')
    monkeypatch.setenv("REPO_ATLAS_REGISTRY", str(reg))
    monkeypatch.setenv("REPO_ATLAS_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("REPO_ATLAS_BASE_URL", "u")
    monkeypatch.setenv("REPO_ATLAS_API_KEY", "k")
    monkeypatch.setenv("REPO_ATLAS_EMBED_MODEL", "m")
    app = build_app()
    assert app is not None
    assert set(TOOL_NAMES) == {"find_related", "prepare_change", "verify_grounding",
                               "list_repos"}
