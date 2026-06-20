from repo_atlas.config import load_config, AtlasConfig


def test_env_overrides_and_defaults(tmp_path):
    env = {
        "REPO_ATLAS_BASE_URL": "http://gw/v1",
        "REPO_ATLAS_API_KEY": "sk-x",
        "REPO_ATLAS_EMBED_MODEL": "bge-m3",
        "REPO_ATLAS_DB": str(tmp_path / "a.db"),
    }
    cfg = load_config(env)
    assert isinstance(cfg, AtlasConfig)
    assert cfg.base_url == "http://gw/v1"
    assert cfg.api_key == "sk-x"
    assert cfg.embed_model == "bge-m3"
    assert cfg.db_path == str(tmp_path / "a.db")


def test_db_path_defaults_under_home():
    cfg = load_config({"REPO_ATLAS_BASE_URL": "u", "REPO_ATLAS_API_KEY": "k",
                       "REPO_ATLAS_EMBED_MODEL": "m"})
    assert cfg.db_path.endswith(".repo_atlas/atlas.db")
