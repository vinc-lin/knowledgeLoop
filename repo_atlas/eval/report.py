from __future__ import annotations


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render_scorecard(scorecard) -> str:
    s = scorecard.summary
    lines = ["# repo_atlas eval — with vs without\n",
             f"Tasks: **{s['n']}**\n",
             "| Metric | baseline | treatment | delta |",
             "|---|---|---|---|",
             f"| **Task success** (primary) | {_pct(s['success_baseline'])} | "
             f"{_pct(s['success_treatment'])} | {s['success_delta']*100:+.0f}pp |",
             f"| Hallucination rate | — | — | {s['hallucination_delta']:+.2f} (lower better) |",
             f"| Prior-art reuse | — | — | {s['reuse_delta']:+.2f} (higher better) |",
             f"| Exploration cost | — | — | {s['exploration_delta']:+.1f} (lower better) |",
             f"\n**Tool adoption (treatment): {s['adoption_mean']:.1f} repo_atlas calls/run; "
             f"{s['adoption_runs']}/{s['n']} runs used the tools** "
             f"{'⚠️ zero adoption → result is null-by-construction' if s['adoption_runs'] == 0 else ''}",
             f"\n**Regressed tasks (treatment worse): {s['regressed_count']}/{s['n']}**\n",
             "## Per-task",
             "| task | success b→t | hallucination b→t | reuse b→t | explore b→t | atlas calls (t) | regressed |",
             "|---|---|---|---|---|---|---|"]
    for p in scorecard.pairs:
        b, t = p.baseline, p.treatment
        lines.append(
            f"| {p.task_id} | {b.success}→{t.success} | "
            f"{b.hallucination_rate:.2f}→{t.hallucination_rate:.2f} | "
            f"{b.reuse_recall:.2f}→{t.reuse_recall:.2f} | "
            f"{b.exploration_cost}→{t.exploration_cost} | {t.atlas_calls} | "
            f"{'YES' if p.regressed else ''} |")
    useful = s["success_delta"] > 0 or (s["hallucination_delta"] < 0 and s["reuse_delta"] > 0)
    lines.append(f"\n## Verdict\nrepo_atlas is **{'useful' if useful else 'NOT clearly useful'}** "
                 f"on this task set (primary = task success).")
    return "\n".join(lines)
