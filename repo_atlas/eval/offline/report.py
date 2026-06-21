# repo_atlas/eval/offline/report.py
from __future__ import annotations


def _f(x) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else str(x)


def _retrieval_section(rep, ks=(5, 10, 20)) -> list:
    if rep is None:
        return ["## Retrieval (find_related)\n_no retrieval layer run._\n"]
    ks = tuple(ks)
    kmax = max(ks)
    succ_cols = [f"Success@{k}" for k in ks]
    header = "| scope | " + " | ".join(succ_cols + ["MRR", f"nDCG@{kmax}"]) + " |"
    sep = "|---" * (len(succ_cols) + 3) + "|"
    mg = rep.overall.get("median_golds")
    title = (f"## Retrieval (find_related) — cases: {rep.overall['n']}"
             + (f"  (median golds/case: {_f(mg)})" if mg is not None else "") + "\n")
    lines = [title, header, sep]

    def row(name, agg):
        cells = [name] + [_f(agg.get(f"success@{k}", 0)) for k in ks]
        cells += [_f(agg.get("mrr", 0)), _f(agg.get(f"ndcg@{kmax}", 0))]
        return "| " + " | ".join(cells) + " |"

    lines.append(row("overall", rep.overall))
    for repo in sorted(rep.per_repo):
        lines.append(row(repo, rep.per_repo[repo]))
    lines.append(f"\n(secondary) coverage Recall@{kmax} (fraction of all acceptable golds): "
                 f"{_f(rep.overall.get(f'recall@{kmax}', 0))} overall")
    sym = rep.overall.get(f"sym_success@{kmax}")
    if sym is not None:
        lines.append(f"(secondary) symbol-level Success@{kmax}: {_f(sym)} overall")
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
                             embed_model: str = "", db_path: str = "",
                             ks=(5, 10, 20)) -> str:
    head = ["# repo_atlas offline eval — retrieval + grounding\n"]
    if embed_model or db_path:
        head.append(f"_embed_model={embed_model or '?'} · db={db_path or '?'}_\n")
    return "\n".join(head + _retrieval_section(retrieval_report, ks)
                     + ["\n"] + _grounding_section(grounding_report)) + "\n"
