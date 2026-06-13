"""Model capability profiles — the model-agnostic backbone.

CodeWiki's operational parameters (output cap, token-param style, agent request
budget, clustering granularity, max depth, temperature) are model-specific but
were historically hardcoded or global. This module makes them declarative and
per-model so switching models is a one-liner.

A :class:`ModelProfile` is resolved from three layers (later non-None wins):
  1. ``PROVIDER_DEFAULTS[provider]`` — coarse defaults per provider.
  2. ``REGISTRY[<model-id substring>]`` — per-model overrides.
  3. an optional user override dict (from ``config.json``'s ``models`` map).

The granularity (clustering thresholds) is *derived from* the output cap — the
key lesson from running DeepSeek (8K output): a leaf module's doc must be
writable in a single ``str_replace_editor`` call, and modules above the cluster
threshold are force-split so the input never balloons to whole-repo size.

Subscription models (Claude Code / Codex, the "caw" path) cannot receive
``max_tokens`` and expose no capability endpoint, so their output cap / request
budget / token-param style are *inert*: granularity + max_depth are the only
levers, and those profiles ship explicit (not derived) granularity.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from typing import Optional

# Which knobs a backend can actually enforce. Informational, and drives the
# `config show` warning that output_cap / request_limit are ignored on caw.
API_HONORED = frozenset({
    "output_cap", "request_limit", "token_param_style", "litellm_prefix",
    "temperature", "cluster_granularity", "leaf_granularity", "max_depth",
})
CAW_HONORED = frozenset({"cluster_granularity", "leaf_granularity", "max_depth"})

# Subscription/no-API-key providers (the caw path) where output cap / request
# limit / token-param style are inert.
SUBSCRIPTION_PROVIDERS = ("claude-code", "codex")

# Stage 6 tuning surface: how clustering granularity is derived from the output cap.
# leaf  ≈ output_cap * LEAF_GRANULARITY_FACTOR   (a leaf doc must fit in one write)
# clust ≈ output_cap * CLUSTER_GRANULARITY_FACTOR (above the cap so larger modules split)
# These are the single empirical knob; tune against live runs once Stage 1 diagnostics
# identify the dominant loop cost. Centralized here so tuning is a one-line change.
LEAF_GRANULARITY_FACTOR = 0.85
CLUSTER_GRANULARITY_FACTOR = 1.4


@dataclass(frozen=True)
class ModelProfile:
    """Per-model operational capabilities. ``None`` means "inherit / not applicable"."""

    output_cap: Optional[int]            # real max OUTPUT tokens; None = provider/CLI decides (caw)
    input_context_window: Optional[int]  # reserved for response-length scaling
    token_param_style: Optional[str]     # "max_tokens" | "max_completion_tokens" | None (caw)
    litellm_prefix: Optional[str]        # "anthropic/" | "bedrock/" | None
    request_limit: Optional[int]         # pydantic-ai UsageLimits; None = no enforced budget (caw)
    cluster_granularity: Optional[int]   # -> Config.max_token_per_module; None = derive from output_cap
    leaf_granularity: Optional[int]      # -> Config.max_token_per_leaf_module; None = derive
    max_depth: int
    temperature: Optional[float]         # None = OMIT the temperature param entirely
    honored: frozenset                   # API_HONORED or CAW_HONORED
    decompose_on_overflow: bool = True   # leaf write overflow -> retry as decompose


def _derive_granularity(p: ModelProfile) -> ModelProfile:
    """Fill clustering thresholds from the output cap when not explicitly set.

    leaf ≈ output_cap * 0.85  — a leaf's doc must fit under the cap in one write.
    cluster ≈ output_cap * 1.4 — deliberately *above* the cap so anything larger
    is force-clustered (avoiding the whole-repo ~1M-token input overflow).
    With no output_cap (caw) there is nothing to derive from, so the profile must
    already carry explicit granularity.
    """
    if p.output_cap is None:
        return p
    cluster = p.cluster_granularity if p.cluster_granularity is not None else int(p.output_cap * CLUSTER_GRANULARITY_FACTOR)
    leaf = p.leaf_granularity if p.leaf_granularity is not None else int(p.output_cap * LEAF_GRANULARITY_FACTOR)
    return replace(p, cluster_granularity=cluster, leaf_granularity=leaf)


# ----------------------------------------------------------------------------
# Provider defaults — coarse per-provider baseline.
# ----------------------------------------------------------------------------
PROVIDER_DEFAULTS: dict[str, ModelProfile] = {
    # token_param_style=None on the generic API providers means "defer to the
    # auto-detect heuristic" so newer OpenAI models (gpt-4o/o1/...) keep working;
    # Azure and specific registry models declare it explicitly where it must differ.
    "openai-compatible": ModelProfile(
        output_cap=None, input_context_window=None, token_param_style=None,
        litellm_prefix=None, request_limit=200, cluster_granularity=None,
        leaf_granularity=None, max_depth=2, temperature=0.0, honored=API_HONORED),
    "anthropic": ModelProfile(
        output_cap=None, input_context_window=None, token_param_style=None,
        litellm_prefix="anthropic/", request_limit=200, cluster_granularity=None,
        leaf_granularity=None, max_depth=2, temperature=0.0, honored=API_HONORED),
    "bedrock": ModelProfile(
        output_cap=None, input_context_window=None, token_param_style=None,
        litellm_prefix="bedrock/", request_limit=200, cluster_granularity=None,
        leaf_granularity=None, max_depth=2, temperature=0.0, honored=API_HONORED),
    "azure-openai": ModelProfile(
        output_cap=None, input_context_window=None, token_param_style="max_completion_tokens",
        litellm_prefix=None, request_limit=200, cluster_granularity=None,
        leaf_granularity=None, max_depth=2, temperature=0.0, honored=API_HONORED),
    # Subscription: output_cap / request_limit / token_param_style are INERT.
    # Ship conservative EXPLICIT granularity so even an unregistered caw model is safe.
    "claude-code": ModelProfile(
        output_cap=None, input_context_window=None, token_param_style=None,
        litellm_prefix=None, request_limit=None, cluster_granularity=16000,
        leaf_granularity=8000, max_depth=2, temperature=None, honored=CAW_HONORED),
    "codex": ModelProfile(
        output_cap=None, input_context_window=None, token_param_style=None,
        litellm_prefix=None, request_limit=None, cluster_granularity=16000,
        leaf_granularity=8000, max_depth=2, temperature=None, honored=CAW_HONORED),
}

# ----------------------------------------------------------------------------
# Per-model registry — keyed by normalized model-id substring. Only NON-None
# fields override the provider default. Values are deliberately set with the
# run-learnings in mind (see comments).
# ----------------------------------------------------------------------------
REGISTRY: dict[str, object] = {
    # DeepSeek (8K output). request_limit is LOW-ish on purpose: a stuck sub-agent
    # should fail fast so the parent module agent back-fills its doc — a high
    # ceiling just wastes ~7-8 min/stuck-module. depth=3 + derived leaf granularity
    # split heavy modules so first writes fit under 8K.
    "deepseek": ModelProfile(
        output_cap=8192, input_context_window=64000, token_param_style="max_tokens",
        litellm_prefix=None, request_limit=300, cluster_granularity=None,
        leaf_granularity=None, max_depth=3, temperature=0.0, honored=API_HONORED),
    # Qwen 3.x (8K output, large input window).
    "qwen": ModelProfile(
        output_cap=8192, input_context_window=131072, token_param_style="max_tokens",
        litellm_prefix=None, request_limit=250, cluster_granularity=None,
        leaf_granularity=None, max_depth=2, temperature=0.0, honored=API_HONORED),
    # Claude Sonnet via API (64K output) — generous granularity ~ today's defaults.
    "claude-sonnet": ModelProfile(
        output_cap=64000, input_context_window=200000, token_param_style="max_tokens",
        litellm_prefix=None, request_limit=200, cluster_granularity=36369,
        leaf_granularity=16000, max_depth=2, temperature=0.0, honored=API_HONORED),
    # Claude Haiku via Claude Code (caw). output_cap is INERT for the param, but
    # the subscription path's effective per-message cap drives SAFE-LOW explicit
    # granularity (the only lever). depth=3 to split aggressively.
    "claude-3-5-haiku": ModelProfile(
        output_cap=None, input_context_window=200000, token_param_style=None,
        litellm_prefix=None, request_limit=None, cluster_granularity=14000,
        leaf_granularity=8000, max_depth=3, temperature=None, honored=CAW_HONORED),
    "claude-haiku": "alias:claude-3-5-haiku",
}


def _normalize(model_name: str) -> str:
    return (model_name or "").lower()


def _registry_match(model_name: str) -> Optional[ModelProfile]:
    """Longest matching substring key in REGISTRY, resolving ``alias:`` indirection."""
    norm = _normalize(model_name)
    # Prefer the longest matching key so "claude-3-5-haiku" beats a hypothetical "claude".
    candidates = sorted(
        (k for k in REGISTRY if k in norm), key=len, reverse=True
    )
    for key in candidates:
        val = REGISTRY[key]
        if isinstance(val, str) and val.startswith("alias:"):
            val = REGISTRY.get(val.split(":", 1)[1])
        if isinstance(val, ModelProfile):
            return val
    return None


def _merge(base: ModelProfile, match: Optional[ModelProfile], user_override: Optional[dict]) -> ModelProfile:
    """Layer profiles: base -> registry match (non-None wins) -> user override dict (present keys win)."""
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(ModelProfile)}
    if match is not None:
        for f in dataclasses.fields(ModelProfile):
            v = getattr(match, f.name)
            if v is not None:
                fields[f.name] = v
    if user_override:
        for k, v in user_override.items():
            if k in fields and v is not None:
                fields[k] = v
    return ModelProfile(**fields)


def resolve_profile(provider: str, model_name: str, user_override: Optional[dict] = None) -> ModelProfile:
    """Resolve the effective :class:`ModelProfile` for ``(provider, model_name)``.

    Subscription providers get a hard inertness mask applied last, so even a user
    override cannot make ``output_cap`` / ``request_limit`` / ``token_param_style``
    silently mislead on a path that ignores them.
    """
    base = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai-compatible"])
    match = _registry_match(model_name)
    merged = _merge(base, match, user_override)
    if provider in SUBSCRIPTION_PROVIDERS:
        merged = replace(
            merged, output_cap=None, token_param_style=None, request_limit=None,
            temperature=None, litellm_prefix=None, honored=CAW_HONORED,
        )
    return _derive_granularity(merged)


def profile_to_config_kwargs(profile: ModelProfile) -> dict:
    """Map a profile to the ``Config`` fields it drives (only non-None values).

    Granularity/output_cap may legitimately be None for an unregistered API model;
    callers should keep their existing defaults in that case.
    """
    kwargs: dict = {
        "token_param_style": profile.token_param_style,
        "litellm_prefix": profile.litellm_prefix,
        "request_limit": profile.request_limit,
        "max_depth": profile.max_depth,
    }
    if profile.output_cap is not None:
        kwargs["max_tokens"] = profile.output_cap
    if profile.cluster_granularity is not None:
        kwargs["max_token_per_module"] = profile.cluster_granularity
    if profile.leaf_granularity is not None:
        kwargs["max_token_per_leaf_module"] = profile.leaf_granularity
    return kwargs
