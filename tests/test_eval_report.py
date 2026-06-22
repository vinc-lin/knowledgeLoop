from repo_atlas.eval.report import render_scorecard
from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate


def test_render_contains_summary_and_per_task():
    base = TaskScore("t1", "baseline", False, 0.6, 0.0, 10)
    treat = TaskScore("t1", "treatment", True, 0.1, 1.0, 4)
    sc = aggregate([make_pair("t1", base, treat)])
    md = render_scorecard(sc)
    assert "Task success" in md
    assert "t1" in md                 # per-task row
    assert "regressed" in md.lower()
    assert "Verdict" in md


def test_render_shows_tool_adoption():
    base = TaskScore("t1", "baseline", True, 0.0, 0.0, 5, 0)
    treat = TaskScore("t1", "treatment", True, 0.0, 0.0, 7, 4)   # 4 repo_atlas calls
    sc = aggregate([make_pair("t1", base, treat)])
    md = render_scorecard(sc)
    assert "adoption" in md.lower()    # adoption surfaced
    assert "1/1" in md                 # 1 of 1 treatment runs used the tools
    assert "→4" in md or " 4 " in md   # per-task atlas-call count visible


def test_render_multi_scorecard_has_arms_contrasts_and_correlation():
    from repo_atlas.eval.aggregate import TaskScore, aggregate_arms
    from repo_atlas.eval.report import render_multi_scorecard

    def ts(arm, ok):
        return TaskScore(task_id="t", condition=arm, success=ok, hallucination_rate=0.0,
                         reuse_recall=0.0, exploration_cost=1)
    per_task = {"t1": {"control": ts("control", False), "optional": ts("optional", False),
                       "forced-inject": ts("forced-inject", True)}}
    sc = aggregate_arms(per_task, ["control", "optional", "forced-inject"])
    corrs = [{"arm": "optional", "n_surfaced": 1, "n_unsurfaced": 0,
              "success_if_surfaced": 0.0, "success_if_not": None}]
    md = render_multi_scorecard(sc, corrs)
    assert "forced-inject" in md and "control" in md
    assert "Arm contrasts" in md and "adoption_tax" in md
    assert "directional only" in md                      # N caveat is explicit
    assert "—" in md                                     # None bucket renders as a dash
