"""Stage 2 verification: ModelProfile registry, resolver, deriver, and Config back-fill."""

import dataclasses

import pytest

from codewiki.src.be.model_profiles import (
    API_HONORED,
    CAW_HONORED,
    PROVIDER_DEFAULTS,
    ModelProfile,
    _derive_granularity,
    resolve_profile,
)
from codewiki.src.config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOKEN_PER_MODULE,
    DEFAULT_MAX_TOKEN_PER_LEAF_MODULE,
    MAX_DEPTH,
    Config,
)


def _cfg(provider, model, **kw):
    return Config(
        repo_path="x", output_dir="o", dependency_graph_dir="d", docs_dir="dd",
        max_depth=MAX_DEPTH, llm_base_url="http://gw/v1", llm_api_key="k",
        main_model=model, cluster_model=model, fallback_model="fb",
        provider=provider, **kw,
    )


# --- deriver math -----------------------------------------------------------

def test_deriver_from_output_cap():
    p = ModelProfile(8192, 64000, "max_tokens", None, 300, None, None, 3, 0.0, API_HONORED)
    d = _derive_granularity(p)
    assert d.leaf_granularity == int(8192 * 0.85) == 6963
    assert d.cluster_granularity == int(8192 * 1.4) == 11468


def test_deriver_noop_without_output_cap():
    # caw profile (output_cap None) must carry explicit granularity; deriver is a no-op.
    p = ModelProfile(None, None, None, None, None, 14000, 8000, 3, None, CAW_HONORED)
    assert _derive_granularity(p) == p


# --- registry resolution ----------------------------------------------------

@pytest.mark.parametrize(
    "provider,model,out,style,req,clust,leaf,depth",
    [
        ("openai-compatible", "deepseek-chat", 8192, "max_tokens", 300, 11468, 6963, 3),
        ("openai-compatible", "qwen3", 8192, "max_tokens", 250, 11468, 6963, 2),
        ("anthropic", "claude-sonnet-4-5", 64000, "max_tokens", 200, 36369, 16000, 2),
    ],
)
def test_api_targets_resolve(provider, model, out, style, req, clust, leaf, depth):
    p = resolve_profile(provider, model)
    assert (p.output_cap, p.token_param_style, p.request_limit) == (out, style, req)
    assert (p.cluster_granularity, p.leaf_granularity, p.max_depth) == (clust, leaf, depth)
    assert p.honored == API_HONORED


def test_alias_resolves():
    assert resolve_profile("claude-code", "claude-haiku") == resolve_profile("claude-code", "claude-3-5-haiku")


def test_longest_substring_match_wins():
    # "claude-3-5-haiku" must win over a bare "claude-*" had one existed; sanity on specificity.
    p = resolve_profile("claude-code", "anthropic/claude-3-5-haiku-20241022")
    assert p.cluster_granularity == 14000 and p.leaf_granularity == 8000


# --- caw inertness ----------------------------------------------------------

def test_caw_inertness_forced():
    # Even if a user override tries to set API-only knobs on a subscription provider,
    # they are forced inert.
    p = resolve_profile("claude-code", "claude-3-5-haiku",
                        {"output_cap": 99999, "request_limit": 123, "token_param_style": "max_tokens"})
    assert p.output_cap is None
    assert p.request_limit is None
    assert p.token_param_style is None
    assert p.temperature is None
    assert p.honored == CAW_HONORED
    # granularity still honored on caw
    assert p.cluster_granularity == 14000 and p.leaf_granularity == 8000


def test_unknown_caw_model_gets_safe_granularity():
    # An unregistered caw model falls back to the provider default's explicit granularity.
    p = resolve_profile("claude-code", "some-future-model")
    assert p.cluster_granularity == 16000 and p.leaf_granularity == 8000
    assert p.request_limit is None


# --- merge precedence -------------------------------------------------------

def test_user_override_wins_on_api():
    p = resolve_profile("openai-compatible", "deepseek-chat",
                        {"request_limit": 400, "leaf_granularity": 6000})
    assert p.request_limit == 400
    assert p.leaf_granularity == 6000  # explicit, not derived


def test_unknown_api_model_uses_provider_default():
    p = resolve_profile("openai-compatible", "mystery-model-7")
    base = PROVIDER_DEFAULTS["openai-compatible"]
    assert p.request_limit == base.request_limit == 200
    assert p.output_cap is None  # nothing to derive from -> granularity stays None
    assert p.cluster_granularity is None and p.leaf_granularity is None


# --- Config __post_init__ back-fill -----------------------------------------

def test_config_autoconfigures_from_deepseek():
    c = _cfg("openai-compatible", "deepseek-chat")
    assert c.max_tokens == 8192
    assert c.max_token_per_module == 11468
    assert c.max_token_per_leaf_module == 6963
    assert c.request_limit == 300
    assert c.max_depth == 3
    assert c.profile is not None


def test_config_caw_inert():
    c = _cfg("claude-code", "claude-3-5-haiku")
    assert c.request_limit is None             # no enforced budget on caw
    assert c.max_token_per_module == 14000     # explicit granularity honored
    assert c.max_token_per_leaf_module == 8000
    assert c.max_depth == 3
    assert "output_cap" not in c.profile.honored


def test_explicit_value_wins_over_profile():
    # User-supplied max_tokens must not be overwritten by the profile's output_cap.
    c = _cfg("openai-compatible", "deepseek-chat", max_tokens=5000)
    assert c.max_tokens == 5000
    # granularity (not explicitly set) is still profile-derived
    assert c.max_token_per_module == 11468


def test_unknown_model_keeps_config_defaults():
    c = _cfg("openai-compatible", "mystery-model-7")
    assert c.max_tokens == DEFAULT_MAX_TOKENS
    assert c.max_token_per_module == DEFAULT_MAX_TOKEN_PER_MODULE
    assert c.max_token_per_leaf_module == DEFAULT_MAX_TOKEN_PER_LEAF_MODULE
    assert c.request_limit == 200
