from __future__ import annotations

from dataclasses import dataclass

from repo_atlas.eval.causal import classify, CATEGORIES


@dataclass
class TaskScore:
    task_id: str
    condition: str             # 'baseline' | 'treatment'
    success: bool
    hallucination_rate: float
    reuse_recall: float
    exploration_cost: int
    atlas_calls: int = 0       # repo_atlas tool calls (treatment adoption signal)
    retrieval_surfaced_gold: bool = False
    reused_prior_art: bool = False


@dataclass
class PairResult:
    task_id: str
    baseline: TaskScore
    treatment: TaskScore
    regressed: bool
    category: str = ""


@dataclass
class Scorecard:
    pairs: list
    summary: dict


def make_pair(task_id: str, baseline: TaskScore, treatment: TaskScore) -> PairResult:
    # 'regressed' = treatment did worse on the primary metric (success), or — when success
    # is unchanged — worse on hallucination.
    if treatment.success != baseline.success:
        regressed = baseline.success and not treatment.success
    else:
        regressed = treatment.hallucination_rate > baseline.hallucination_rate
    category = classify(b=baseline.success, t=treatment.success,
                        surfaced=treatment.retrieval_surfaced_gold,
                        reused=treatment.reused_prior_art, adopted=treatment.atlas_calls > 0)
    return PairResult(task_id, baseline, treatment, regressed, category)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(pairs: list) -> Scorecard:
    b = [p.baseline for p in pairs]
    t = [p.treatment for p in pairs]
    summary = {
        "n": len(pairs),
        "success_baseline": _mean([1.0 if s.success else 0.0 for s in b]),
        "success_treatment": _mean([1.0 if s.success else 0.0 for s in t]),
        "hallucination_delta": _mean([s.hallucination_rate for s in t]) - _mean([s.hallucination_rate for s in b]),
        "reuse_delta": _mean([s.reuse_recall for s in t]) - _mean([s.reuse_recall for s in b]),
        "exploration_delta": _mean([s.exploration_cost for s in t]) - _mean([s.exploration_cost for s in b]),
        "regressed_count": sum(1 for p in pairs if p.regressed),
        # Adoption: did the treatment agent actually CALL the repo_atlas tools? A null result
        # is only interpretable if adoption > 0 (else treatment == baseline by construction).
        "adoption_mean": _mean([s.atlas_calls for s in t]),
        "adoption_runs": sum(1 for s in t if s.atlas_calls > 0),
        "causal_wins": sum(1 for p in pairs if p.category == "causal-win"),
        "categories": {c: sum(1 for p in pairs if p.category == c) for c in CATEGORIES},
        "surfaced_rate": _mean([1.0 if s.retrieval_surfaced_gold else 0.0 for s in t]),
        "reused_rate": _mean([1.0 if s.reused_prior_art else 0.0 for s in t]),
    }
    summary["success_delta"] = summary["success_treatment"] - summary["success_baseline"]
    return Scorecard(pairs=pairs, summary=summary)


@dataclass
class MultiScorecard:
    per_task: dict          # task_id -> {arm -> TaskScore}
    arms: list              # arm order
    summary: dict


def aggregate_arms(per_task: dict, arms: list) -> MultiScorecard:
    """Per-arm grounded-success + the three loop-decomposing contrasts. `per_task` maps
    task_id -> {arm -> TaskScore}; arms missing from a task are skipped for that arm's mean."""
    by_arm = {a: [pt[a] for pt in per_task.values() if a in pt] for a in arms}
    succ = {a: _mean([1.0 if s.success else 0.0 for s in by_arm[a]]) for a in arms}
    summary = {
        "n": len(per_task),
        "success": succ,
        "adoption_runs": {a: sum(1 for s in by_arm[a] if s.atlas_calls > 0) for a in arms},
        "surfaced_rate": {a: _mean([1.0 if s.retrieval_surfaced_gold else 0.0 for s in by_arm[a]])
                          for a in arms},
        # mean exploration cost (turn-count proxy) per arm: the over-steering signal — a nudge
        # that balloons turns on locally-solvable tasks shows up as assisted >> control here.
        "exploration": {a: _mean([s.exploration_cost for s in by_arm[a]]) for a in arms},
        "contrasts": {},
    }
    if "forced-inject" in arms and "control" in arms:
        summary["contrasts"]["ceiling (forced−control)"] = succ["forced-inject"] - succ["control"]
    if "optional" in arms and "control" in arms:
        summary["contrasts"]["captured (optional−control)"] = succ["optional"] - succ["control"]
    if "forced-inject" in arms and "optional" in arms:
        summary["contrasts"]["adoption_tax (forced−optional)"] = succ["forced-inject"] - succ["optional"]
    if "assisted" in arms and "control" in arms:
        summary["contrasts"]["assisted_lift (assisted−control)"] = succ["assisted"] - succ["control"]
    if "forced-inject" in arms and "assisted" in arms:
        summary["contrasts"]["assist_gap (forced−assisted)"] = succ["forced-inject"] - succ["assisted"]
    return MultiScorecard(per_task, arms, summary)
