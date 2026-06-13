"""Stage 3 verification: per-model override map round-trips and drives to_backend_config."""

from codewiki.cli.models.config import Configuration
from codewiki.src.be.model_profiles import CAW_HONORED, resolve_profile


def _config(**kw):
    base = dict(base_url="http://gw/v1", main_model="deepseek-chat", cluster_model="deepseek-chat")
    base.update(kw)
    return Configuration(**base)


def test_models_map_round_trips():
    c = _config()
    c.models["deepseek-chat"] = {"request_limit": 400, "leaf_granularity": 6000}
    d = c.to_dict()
    assert d["models"] == {"deepseek-chat": {"request_limit": 400, "leaf_granularity": 6000}}
    assert Configuration.from_dict(d).models == c.models


def test_empty_models_not_serialized():
    c = _config()
    assert "models" not in c.to_dict()


def test_legacy_flat_config_loads():
    # Old config.json without a 'models' key must load unchanged (no migration).
    legacy = Configuration.from_dict({"base_url": "u", "main_model": "m", "cluster_model": "m"})
    assert legacy.models == {}


def test_override_drives_backend_config():
    c = _config()
    c.models["deepseek-chat"] = {"request_limit": 400, "leaf_granularity": 6000}
    bc = c.to_backend_config(repo_path=".", output_dir="./x", api_key="k")
    assert bc.request_limit == 400
    assert bc.max_token_per_leaf_module == 6000
    assert bc.profile is not None


def test_backend_config_autoconfigures_without_override():
    c = _config()
    bc = c.to_backend_config(repo_path=".", output_dir="./x", api_key="k")
    # deepseek profile applied even though Configuration carries the stale defaults.
    assert bc.max_tokens == 8192
    assert bc.max_token_per_module == 11468
    assert bc.request_limit == 300
    assert bc.max_depth == 3


def test_caw_provider_profile_is_inert():
    c = _config(provider="claude-code", main_model="claude-3-5-haiku")
    prof = resolve_profile(c.provider, c.main_model, c.models.get(c.main_model))
    assert prof.honored == CAW_HONORED
    bc = c.to_backend_config(repo_path=".", output_dir="./x", api_key="k")
    assert bc.request_limit is None
    assert bc.max_token_per_module == 14000
