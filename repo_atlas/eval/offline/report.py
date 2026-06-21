# repo_atlas/eval/offline/report.py
from __future__ import annotations


def _f(x) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else str(x)


def _retrieval_section(rep, ks=(5, 10, 20)) -> list:
    if rep is None:
        return ["## Retrieval (find_related)\n_no retrieval layer run._\n"]
    lines = [f"## Retrieval (find_related) — cases: {rep.overall['n']}\n",
             "| scope | Recall@5 | Recall@10 | Recall@20 | Hit@10 | MRR | nDCG@10 |",
             "|---|---|---|---|---|---|---|"]

    def row(name, agg):
        return (f"| {name} | {_f(agg.get('recall@5', 0))} | {_f(agg.get('recall@10', 0))} | "
                f"{_f(agg.get('recall@20', 0))} | {_f(agg.get('hit@10', 0))} | "
                f"{_f(agg.get('mrr', 0))} | {_f(agg.get('ndcg@10', 0))} |")

    lines.append(row("overall", rep.overall))
    for repo in sorted(rep.per_repo):
        lines.append(row(repo, rep.per_repo[repo]))
    sym = rep.overall.get(f"sym_recall@{max(ks)}")
    if sym is not None:
        lines.append(f"\n(secondary) symbol-level Recall@{max(ks)} overall: {_f(sym)}")
    return lines


def _grounding_section(rep) -> list:
    if rep is None:
        return ["## Grounding (verify_grounding)\n_no grounding layer run._\n"]
    lines = [f"## Grounding (verify_grounding) — cases: {rep.overall['n']}\n",
             "| scope | sensitivity | specificity |", "|---|---|---|",
             f"| overall | {_f(rep.overall['sensitivity'])} | {_f(rep.overall['specificity'])} |"]
    for repo in sorted(rep.per_repo):
        a = rep.per_repo[repo]
        lines.append(f"| {repo} | {_f(a['sensitivity'])} | {_f(a['specificity'])} |")
    if rep.false_negatives:
        lines.append("\n**Worst false-negatives (real symbols reported missing):**")
        for repo in sorted(rep.false_negatives):
            fns = rep.false_negatives[repo]
            lines.append(f"- {repo}: {', '.join(fns[:20])}" + (" …" if len(fns) > 20 else ""))
    return lines


def render_offline_scorecard(retrieval_report, grounding_report, *,
                             embed_model: str = "", db_path: str = "") -> str:
    head = ["# repo_atlas offline eval — retrieval + grounding\n"]
    if embed_model or db_path:
        head.append(f"_embed_model={embed_model or '?'} · db={db_path or '?'}_\n")
    return "\n".join(head + _retrieval_section(retrieval_report)
                     + ["\n"] + _grounding_section(grounding_report)) + "\n"
