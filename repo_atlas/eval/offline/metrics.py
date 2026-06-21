from __future__ import annotations

import math


def recall_at_k(ranked_files: list, gold: set, k: int) -> float:
    """Fraction of gold files present among the top-k ranked files. 0.0 if gold empty."""
    if not gold:
        return 0.0
    topk = set(ranked_files[:k])
    return len(gold & topk) / len(gold)


def success_at_k(ranked_files: list, gold: set, k: int) -> float:
    """1.0 if any acceptable gold file is in the top-k, else 0.0 (any-of relevance)."""
    return 1.0 if (gold & set(ranked_files[:k])) else 0.0


def mrr(ranked_files: list, gold: set) -> float:
    """Reciprocal rank (1-indexed) of the first gold file in the FULL list. 0.0 if none."""
    for i, f in enumerate(ranked_files):
        if f in gold:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked_files: list, gold: set, k: int) -> float:
    """Binary, file-level, dedup nDCG@k (each gold file rewarded once)."""
    if not gold:
        return 0.0
    dcg, seen = 0.0, set()
    for i, f in enumerate(ranked_files[:k]):
        if f in gold and f not in seen:
            seen.add(f)
            dcg += 1.0 / math.log2(i + 2)        # position p=i+1 -> 1/log2(p+1)
    ideal_hits = min(k, len(gold))
    idcg = sum(1.0 / math.log2(p + 1) for p in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def symbol_success_at_k(hits: list, gold_symbols, k: int) -> float:
    """1.0 if any gold symbol (by name or qualified_name) appears in the top-k hits."""
    gold = set(gold_symbols)
    if not gold:
        return 0.0
    for h in hits[:k]:
        if h.get("name") in gold or h.get("qualified_name") in gold:
            return 1.0
    return 0.0


def grounding_scores(verify_result: dict, real: list, fake: list) -> dict:
    """sensitivity = recall over real (source-verified) symbols; specificity over fakes."""
    def _exists(s):
        return bool(verify_result.get(s, {}).get("exists"))
    sens = (sum(1 for s in real if _exists(s)) / len(real)) if real else 0.0
    spec = (sum(1 for s in fake if not _exists(s)) / len(fake)) if fake else 0.0
    fn = [s for s in real if not _exists(s)]
    return {"sensitivity": sens, "specificity": spec, "false_negatives": fn}
