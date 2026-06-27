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
    cats = s.get("categories", {})
    lines += ["\n## Mechanism (causal trace)",
              f"**Causal wins (surfaced + reused + beat baseline): {s.get('causal_wins', 0)}/{s['n']}**  "
              f"· surfaced {s.get('surfaced_rate', 0)*100:.0f}% · reused {s.get('reused_rate', 0)*100:.0f}%\n",
              "| category | count |", "|---|---|"]
    lines += [f"| {c} | {n} |" for c, n in cats.items() if n]
    lines += ["\n| task | success b→t | surfaced | reused | category |",
              "|---|---|---|---|---|"]
    for p in scorecard.pairs:
        lines.append(f"| {p.task_id} | {p.baseline.success}→{p.treatment.success} | "
                     f"{'Y' if p.treatment.retrieval_surfaced_gold else '·'} | "
                     f"{'Y' if p.treatment.reused_prior_art else '·'} | {p.category} |")
    useful = s["success_delta"] > 0 or (s["hallucination_delta"] < 0 and s["reuse_delta"] > 0)
    lines.append(f"\n## Verdict\nrepo_atlas is **{'useful' if useful else 'NOT clearly useful'}** "
                 f"on this task set (primary = task success).")
    return "\n".join(lines)


def render_multi_scorecard(scorecard, correlations=None) -> str:
    """Markdown for the multi-arm outcome-driven eval: per-arm grounded-success, the loop
    contrasts, and (optional) the proxy↔outcome correlation with an explicit small-N caveat."""
    s = scorecard.summary
    arms = scorecard.arms
    lines = ["# repo_atlas eval — multi-arm (outcome-driven)\n",
             f"Tasks: **{s['n']}**  ·  arms: {', '.join(arms)}\n",
             "| arm | grounded-success | adoption (runs) | surfaced | turns |",
             "|---|---|---|---|---|"]
    expl = s.get("exploration", {})
    for a in arms:
        lines.append(f"| {a} | {_pct(s['success'][a])} | "
                     f"{s['adoption_runs'][a]}/{s['n']} | {_pct(s['surfaced_rate'][a])} | "
                     f"{expl.get(a, 0.0):.1f} |")
    lines.append("\n## Arm contrasts")
    for label, val in s["contrasts"].items():
        lines.append(f"- **{label}**: {val * 100:+.0f}pp")
    if correlations:
        lines += ["\n## Proxy → outcome correlation",
                  f"_N={s['n']}, directional only (small sample)._\n",
                  "| arm | success if surfaced | success if not | n surfaced/not |",
                  "|---|---|---|---|"]
        for cr in correlations:
            sif = "—" if cr["success_if_surfaced"] is None else _pct(cr["success_if_surfaced"])
            nif = "—" if cr["success_if_not"] is None else _pct(cr["success_if_not"])
            lines.append(f"| {cr['arm']} | {sif} | {nif} | "
                         f"{cr['n_surfaced']}/{cr['n_unsurfaced']} |")
    return "\n".join(lines)
