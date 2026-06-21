# tests/test_eval_causal.py
from repo_atlas.eval.causal import classify


def test_causal_win():
    assert classify(b=False, t=True, surfaced=True, reused=True, adopted=True) == "causal-win"


def test_win_unattributed():
    assert classify(b=False, t=True, surfaced=False, reused=False, adopted=True) == "win-unattributed"


def test_regression():
    assert classify(b=True, t=False, surfaced=True, reused=True, adopted=True) == "regression"


def test_surfaced_ignored():
    assert classify(b=True, t=True, surfaced=True, reused=False, adopted=True) == "surfaced-ignored"


def test_retrieval_miss():
    assert classify(b=False, t=False, surfaced=False, reused=False, adopted=True) == "retrieval-miss"


def test_no_effect():
    assert classify(b=True, t=True, surfaced=False, reused=False, adopted=False) == "no-effect"
