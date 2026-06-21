from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate


def _score(cond, success, hall, reuse, expl):
    return TaskScore(task_id="t1", condition=cond, success=success,
                     hallucination_rate=hall, reuse_recall=reuse, exploration_cost=expl)


def test_make_pair_regression_flag():
    base = _score("baseline", success=False, hall=0.5, reuse=0.0, expl=10)
    treat = _score("treatment", success=True, hall=0.0, reuse=1.0, expl=4)
    pair = make_pair("t1", base, treat)
    assert pair.regressed is False     # treatment improved on success

    base2 = _score("baseline", success=True, hall=0.0, reuse=1.0, expl=4)
    treat2 = _score("treatment", success=False, hall=0.5, reuse=0.0, expl=10)
    assert make_pair("t1", base2, treat2).regressed is True   # treatment worse on success


def test_aggregate_summary():
    base = _score("baseline", success=False, hall=0.6, reuse=0.0, expl=10)
    treat = _score("treatment", success=True, hall=0.1, reuse=1.0, expl=4)
    sc = aggregate([make_pair("t1", base, treat)])
    s = sc.summary
    assert s["n"] == 1
    assert s["success_baseline"] == 0.0 and s["success_treatment"] == 1.0
    assert s["hallucination_delta"] == -0.5    # treatment - baseline (lower is better)
    assert s["reuse_delta"] == 1.0
    assert s["regressed_count"] == 0


def test_aggregate_reports_treatment_adoption():
    # adoption = did the treatment agent actually CALL the repo_atlas tools?
    base1 = TaskScore("t1", "baseline", False, 0.5, 0.0, 10, 0)
    treat1 = TaskScore("t1", "treatment", True, 0.1, 1.0, 12, 3)   # used tools 3x
    base2 = TaskScore("t2", "baseline", True, 0.0, 0.0, 5, 0)
    treat2 = TaskScore("t2", "treatment", True, 0.0, 0.0, 6, 0)    # never used tools
    sc = aggregate([make_pair("t1", base1, treat1), make_pair("t2", base2, treat2)])
    s = sc.summary
    assert s["adoption_mean"] == 1.5     # (3 + 0) / 2
    assert s["adoption_runs"] == 1       # 1 of 2 treatment runs called a tool


def test_aggregate_classifies_and_counts_mechanism():
    from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate
    base = TaskScore("t1", "baseline", success=False, hallucination_rate=0.0,
                     reuse_recall=0.0, exploration_cost=10)
    treat = TaskScore("t1", "treatment", success=True, hallucination_rate=0.0,
                      reuse_recall=0.0, exploration_cost=8, atlas_calls=2,
                      retrieval_surfaced_gold=True, reused_prior_art=True)
    sc = aggregate([make_pair("t1", base, treat)])
    assert sc.pairs[0].category == "causal-win"
    assert sc.summary["causal_wins"] == 1
    assert sc.summary["categories"]["causal-win"] == 1
    assert sc.summary["surfaced_rate"] == 1.0 and sc.summary["reused_rate"] == 1.0
