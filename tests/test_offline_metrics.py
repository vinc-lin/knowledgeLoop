import math
from repo_atlas.eval.offline import metrics as m


def test_recall_at_k_file_level():
    ranked = ["a.h", "x.cpp", "b.h", "y.cpp"]
    gold = {"a.h", "b.h", "z.h"}
    assert m.recall_at_k(ranked, gold, k=2) == 1 / 3          # only a.h in top-2
    assert m.recall_at_k(ranked, gold, k=4) == 2 / 3          # a.h + b.h
    assert m.recall_at_k(ranked, set(), k=4) == 0.0           # empty gold guarded
    assert m.recall_at_k([], {"a.h"}, k=4) == 0.0


def test_hit_rate_at_k():
    assert m.hit_rate_at_k(["x", "a.h"], {"a.h"}, k=2) == 1.0
    assert m.hit_rate_at_k(["x", "a.h"], {"a.h"}, k=1) == 0.0


def test_mrr_uses_full_list():
    assert m.mrr(["x", "y", "a.h"], {"a.h"}) == 1 / 3
    assert m.mrr(["a.h", "y"], {"a.h"}) == 1.0
    assert m.mrr(["x", "y"], {"a.h"}) == 0.0


def test_ndcg_dedup_and_ideal():
    # one gold file at rank 1 (ideal) -> 1.0
    assert m.ndcg_at_k(["a.h", "x"], {"a.h"}, k=2) == 1.0
    # gold at rank 2 only: DCG = 1/log2(3); IDCG = 1/log2(2)=1
    got = m.ndcg_at_k(["x", "a.h"], {"a.h"}, k=2)
    assert math.isclose(got, (1 / math.log2(3)) / 1.0)
    # duplicate gold file counted once (dedup): second a.h contributes 0
    g2 = m.ndcg_at_k(["a.h", "a.h"], {"a.h"}, k=2)
    assert g2 == 1.0


def test_symbol_recall_at_k():
    hits = [{"name": "Foo", "qualified_name": "ns.Foo"},
            {"name": "Bar", "qualified_name": None}]
    assert m.symbol_recall_at_k(hits, ["Foo", "Bar", "Baz"], k=2) == 2 / 3
    assert m.symbol_recall_at_k(hits, ["ns.Foo"], k=2) == 1.0     # matches qualified_name
    assert m.symbol_recall_at_k(hits, [], k=2) == 0.0


def test_grounding_scores():
    v = {"Real1": {"exists": True}, "Real2": {"exists": False},   # Real2 = false negative
         "Fake1": {"exists": False}, "Fake2": {"exists": True}}   # Fake2 = false positive
    sc = m.grounding_scores(v, ["Real1", "Real2"], ["Fake1", "Fake2"])
    assert sc["sensitivity"] == 0.5
    assert sc["specificity"] == 0.5
    assert sc["false_negatives"] == ["Real2"]
