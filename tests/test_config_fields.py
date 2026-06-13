"""Stage 0 verification: operational knobs are Config fields with behavior-preserving defaults."""

import dataclasses

from codewiki.src.config import Config, MAX_DEPTH
from codewiki.src.be.llm_services import build_usage_limits, _param_style_for, _temperature_for


def _cfg(model="deepseek-chat", provider="openai-compatible", base_url="http://gw/v1", **kw):
    return Config(
        repo_path="x", output_dir="o", dependency_graph_dir="d", docs_dir="dd",
        max_depth=MAX_DEPTH, llm_base_url=base_url, llm_api_key="k",
        main_model=model, cluster_model=model, fallback_model="fb",
        provider=provider, **kw,
    )


def test_new_fields_exist_with_defaults():
    c = _cfg("mystery-model")  # unregistered -> defaults survive
    assert c.token_param_style == "max_tokens"
    assert c.litellm_prefix is None
    assert c.request_limit == 200


def test_build_usage_limits_default():
    c = _cfg("mystery-model")
    ul = build_usage_limits(c)
    assert ul is not None and ul.request_limit == 200


def test_build_usage_limits_none_means_no_budget():
    c = dataclasses.replace(_cfg("mystery-model"), request_limit=None)
    assert build_usage_limits(c) is None


def test_param_style_preserves_gpt4o_heuristic():
    # No profile override for gpt-4o on a generic gateway: heuristic still picks completion tokens.
    c = _cfg("mystery-model")  # token_param_style stays "max_tokens"
    assert _param_style_for(c, "gpt-4o") == "max_completion_tokens"
    assert _param_style_for(c, "deepseek-chat") == "max_tokens"


def test_temperature_default_preserved_without_profile():
    # _temperature_for falls back to 0.0 when no profile drives it.
    c = _cfg("mystery-model")
    # mystery-model still resolves a provider-default profile (temp 0.0)
    assert _temperature_for(c) == 0.0


def test_from_cli_threads_new_fields():
    c = Config.from_cli(
        repo_path=".", output_dir="./out", llm_base_url="http://gw/v1", llm_api_key="k",
        main_model="mystery-model", cluster_model="mystery-model",
        request_limit=42, token_param_style="max_completion_tokens", litellm_prefix="anthropic/",
    )
    assert c.request_limit == 42                       # explicit, not overwritten
    assert c.token_param_style == "max_completion_tokens"
    assert c.litellm_prefix == "anthropic/"
