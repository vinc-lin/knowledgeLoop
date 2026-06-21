from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TaskScore:
    task_id: str
    condition: str             # 'baseline' | 'treatment'
    success: bool
    hallucination_rate: float
    reuse_recall: float
    exploration_cost: int
    atlas_calls: int = 0       # repo_atlas tool calls (treatment adoption signal)


@dataclass
class PairResult:
    task_id: str
    baseline: TaskScore
    treatment: TaskScore
    regressed: bool


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
    return PairResult(task_id, baseline, treatment, regressed)


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
    }
    summary["success_delta"] = summary["success_treatment"] - summary["success_baseline"]
    return Scorecard(pairs=pairs, summary=summary)
