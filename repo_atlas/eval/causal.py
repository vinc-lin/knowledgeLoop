from __future__ import annotations

CATEGORIES = ("causal-win", "win-unattributed", "regression",
              "surfaced-ignored", "retrieval-miss", "no-effect")


def classify(*, b: bool, t: bool, surfaced: bool, reused: bool, adopted: bool) -> str:
    """Per-task causal category (first match wins). See the design spec for the taxonomy.
    b/t = baseline/treatment success; surfaced/reused/adopted are treatment-side signals."""
    if t and not b and surfaced and reused:
        return "causal-win"
    if t and not b:
        return "win-unattributed"
    if b and not t:
        return "regression"
    if surfaced and not reused:
        return "surfaced-ignored"
    if adopted and not surfaced:
        return "retrieval-miss"
    return "no-effect"
