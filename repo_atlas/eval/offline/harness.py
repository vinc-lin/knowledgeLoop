# repo_atlas/eval/offline/harness.py
from __future__ import annotations

from dataclasses import dataclass
import statistics

from repo_atlas.eval.offline import metrics


@dataclass
class RetrievalReport:
    per_case: list
    overall: dict
    per_repo: dict


@dataclass
class GroundingReport:
    per_case: list
    overall: dict
    per_repo: dict
    false_negatives: dict


def _agg_retrieval(rows: list, ks) -> dict:
    out = {"n": len(rows)}
    keys = ([f"success@{k}" for k in ks] + [f"recall@{k}" for k in ks]
            + [f"ndcg@{k}" for k in ks] + ["mrr"])
    for key in keys:
        vals = [r[key] for r in rows if key in r]
        out[key] = sum(vals) / len(vals) if vals else 0.0
    sym_key = f"sym_success@{max(ks)}"
    sym_vals = [r[sym_key] for r in rows if sym_key in r]
    if sym_vals:
        out[sym_key] = sum(sym_vals) / len(sym_vals)
    golds = [r["n_golds"] for r in rows if "n_golds" in r]
    if golds:
        out["median_golds"] = statistics.median(golds)
    return out


async def run_retrieval(cases: list, retriever, ks=(5, 10, 20)) -> RetrievalReport:
    kmax = max(ks)
    per_case = []
    for c in cases:
        try:
            hits = await retriever.retrieve(c.query, c.repo, kmax)
        except Exception as exc:                       # noqa: BLE001 - resilience boundary
            print(f"[offline-eval] case {c.id} failed: {type(exc).__name__}: {exc}")
            continue
        ranked_files = [h.get("file") for h in hits]
        gold_f = set(c.gold_files)
        row = {"id": c.id, "repo": c.repo, "source": c.source, "n_golds": len(gold_f)}
        for k in ks:
            row[f"success@{k}"] = metrics.success_at_k(ranked_files, gold_f, k)
            row[f"recall@{k}"] = metrics.recall_at_k(ranked_files, gold_f, k)   # secondary coverage
            row[f"ndcg@{k}"] = metrics.ndcg_at_k(ranked_files, gold_f, k)
        row["mrr"] = metrics.mrr(ranked_files, gold_f)
        if c.gold_symbols:
            row[f"sym_success@{kmax}"] = metrics.symbol_success_at_k(hits, c.gold_symbols, kmax)
        per_case.append(row)
    repos = sorted({r["repo"] for r in per_case})
    per_repo = {rp: _agg_retrieval([r for r in per_case if r["repo"] == rp], ks) for rp in repos}
    return RetrievalReport(per_case, _agg_retrieval(per_case, ks), per_repo)


def _agg_grounding(rows: list) -> dict:
    out = {"n": len(rows)}
    for key in ("sensitivity", "specificity"):
        vals = [r[key] for r in rows]
        out[key] = sum(vals) / len(vals) if vals else 0.0
    return out


def run_grounding(cases: list, retriever) -> GroundingReport:
    per_case, fn_by_repo = [], {}
    for c in cases:
        v = retriever.ground(c.repo, list(c.real_symbols) + list(c.fake_symbols))
        sc = metrics.grounding_scores(v, list(c.real_symbols), list(c.fake_symbols))
        per_case.append({"id": c.id, "repo": c.repo,
                         "sensitivity": sc["sensitivity"], "specificity": sc["specificity"]})
        if sc["false_negatives"]:
            fn_by_repo.setdefault(c.repo, []).extend(sc["false_negatives"])
    repos = sorted({r["repo"] for r in per_case})
    per_repo = {rp: _agg_grounding([r for r in per_case if r["repo"] == rp]) for rp in repos}
    return GroundingReport(per_case, _agg_grounding(per_case), per_repo, fn_by_repo)
