"""Discipline guards over the cross-repo task corpora (tasks-xrepo*).

The N>=20 count assertion is added in (a2) once tasks are authored; this file currently
enforces the (c) "intent-only retrieval_query" rule: a task's retrieval_query must describe
the INTENT and never name the answer API (else forced-inject/the proxy is teaching-to-test).
"""
import glob
import os
import re

from repo_atlas.eval.tasks import load_tasks

_HERE = os.path.dirname(__file__)
_EVAL = os.path.join(_HERE, "..", "repo_atlas", "eval")
_XREPO_DIRS = sorted(glob.glob(os.path.join(_EVAL, "tasks-xrepo*")))


def _all_xrepo_tasks():
    tasks = []
    for d in _XREPO_DIRS:
        tasks.extend(load_tasks(d))
    return tasks


def test_retrieval_query_is_intent_only_never_names_the_api():
    offenders = []
    for t in _all_xrepo_tasks():
        if not t.retrieval_query:
            continue
        q = t.retrieval_query.lower()
        for api in t.required_apis:
            bare = api.split("::")[-1].lower()
            if re.search(r"\b" + re.escape(bare) + r"\b", q):
                offenders.append((t.id, api))
    assert not offenders, f"retrieval_query names the answer API (teach-to-test): {offenders}"
