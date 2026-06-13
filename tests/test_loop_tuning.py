"""Stage 6 verification: tunable granularity factors + separate sub-agent request budget."""

import dataclasses

from codewiki.src.be import model_profiles
from codewiki.src.be.model_profiles import (
    CLUSTER_GRANULARITY_FACTOR,
    LEAF_GRANULARITY_FACTOR,
    resolve_profile,
)
from codewiki.src.config import Config, MAX_DEPTH
from codewiki.src.be.llm_services import build_usage_limits


def _cfg(**kw):
    return Config(
        repo_path="x", output_dir="o", dependency_graph_dir="d", docs_dir="dd",
        max_depth=MAX_DEPTH, llm_base_url="http://gw/v1", llm_api_key="k",
        main_model="deepseek-chat", cluster_model="deepseek-chat", fallback_model="fb",
        provider="openai-compatible", **kw,
    )


def test_factors_drive_derivation():
    p = resolve_profile("openai-compatible", "deepseek-chat")
    assert p.leaf_granularity == int(8192 * LEAF_GRANULARITY_FACTOR)
    assert p.cluster_granularity == int(8192 * CLUSTER_GRANULARITY_FACTOR)


def test_factor_is_single_tuning_surface(monkeypatch):
    # Changing the constant changes the derived granularity — proving it's the knob.
    monkeypatch.setattr(model_profiles, "LEAF_GRANULARITY_FACTOR", 0.5)
    p = resolve_profile("openai-compatible", "deepseek-chat")
    assert p.leaf_granularity == int(8192 * 0.5)


def test_sub_budget_defaults_to_request_limit():
    c = _cfg()  # deepseek profile -> request_limit 300, sub_request_limit None
    assert c.request_limit == 300
    assert c.sub_request_limit is None
    top = build_usage_limits(c, sub=False)
    sub = build_usage_limits(c, sub=True)
    assert top.request_limit == 300
    assert sub.request_limit == 300  # inherits when sub_request_limit is None


def test_sub_budget_override():
    c = dataclasses.replace(_cfg(), sub_request_limit=40)
    assert build_usage_limits(c, sub=False).request_limit == 300  # top unchanged
    assert build_usage_limits(c, sub=True).request_limit == 40    # sub-agents fail fast


def test_no_budget_when_request_limit_none():
    c = dataclasses.replace(_cfg(), request_limit=None, sub_request_limit=None)
    assert build_usage_limits(c, sub=False) is None
    assert build_usage_limits(c, sub=True) is None
