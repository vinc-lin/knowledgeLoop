from __future__ import annotations

from repo_atlas.eval.tasks import task_query


async def compute_proxy(tasks, retriever, *, k: int = 10) -> dict:
    """Per-task offline proxy signal: is the task's required_api in the SYMBOL-kind retrieval
    top-K (the lap-6b doc-free symbol-rank check). Tasks with no required_apis -> False.
    `retriever.retrieve(query, repo, k, kinds=...)` returns find_related units."""
    out = {}
    for t in tasks:
        surfaced = False
        if t.required_apis:
            # all-repos + focused query, mirroring the forced-inject arm (cross-repo reachable).
            hits = await retriever.retrieve(task_query(t), None, k, kinds=["symbol"])
            names = {h.get("name") for h in hits} | {h.get("qualified_name") for h in hits}
            surfaced = any(api in names or api.split("::")[-1] in names
                           for api in t.required_apis)
        out[t.id] = surfaced
    return out


def correlate(proxy_by_task: dict, scorecard, arm: str) -> dict:
    """For one arm: grounded-success rate conditioned on whether the proxy surfaced the API.
    `None` rate when a bucket is empty. Directional only at small N."""
    yes = [pt[arm] for tid, pt in scorecard.per_task.items()
           if arm in pt and proxy_by_task.get(tid)]
    no = [pt[arm] for tid, pt in scorecard.per_task.items()
          if arm in pt and not proxy_by_task.get(tid)]

    def rate(xs):
        return sum(1 for s in xs if s.success) / len(xs) if xs else None

    return {"arm": arm, "n_surfaced": len(yes), "n_unsurfaced": len(no),
            "success_if_surfaced": rate(yes), "success_if_not": rate(no)}
