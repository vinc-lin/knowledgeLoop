# tests/test_eval_mechanism.py
import json
from repo_atlas.eval.runner import _collect_files, RunResult


def test_collect_files_walks_buckets_and_json_strings():
    out = set()
    # structured envelope
    _collect_files({"result": {"docs": [{"file": "d.md"}],
                               "symbols": [{"file": "s.h"}, {"file": "s.cpp"}]}}, out)
    # a tool_result content that is a JSON *string*
    _collect_files(json.dumps({"result": {"symbols": [{"file": "x.h"}]}}), out)
    assert out == {"d.md", "s.h", "s.cpp", "x.h"}


def test_collect_files_ignores_non_files():
    out = set()
    _collect_files({"query": "no files here", "score": 0.5}, out)
    assert out == set()


def test_runresult_mechanism_defaults():
    r = RunResult("baseline", [], [], 0, 0, {}, "")
    assert r.find_related_queries == [] and r.retrieval_surfaced_gold is False
