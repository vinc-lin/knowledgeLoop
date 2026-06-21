# tests/test_eval_mechanism.py
import json

from repo_atlas.eval import runner
from repo_atlas.eval.runner import _collect_files, _find_related_files_for_session, RunResult


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


def test_find_related_files_walks_separate_use_and_result_lines(tmp_path, monkeypatch):
    """Regression: in real transcripts the tool_use call and its tool_result are on SEPARATE
    lines, and the result line does NOT contain the substring 'find_related' (it references the
    call only via tool_use_id). The extractor must still surface the returned files."""
    session_id = "sess-1234"
    proj = tmp_path / ".claude" / "projects" / "-some-proj"
    proj.mkdir(parents=True)
    use_id = "toolu_ABC"
    # Line 1: the find_related tool_use (assistant turn).
    use_line = {"message": {"content": [
        {"type": "tool_use", "name": "mcp__repo-atlas__find_related",
         "id": use_id, "input": {"query": "JNI registration", "k": 30}}]}}
    # Line 2: the separate tool_result (user turn). Note: no "find_related" substring here; the
    # files live inside a JSON *string* nested in a {"type":"text"} block (the real shape).
    payload = json.dumps({"result": [{"file": "a.cpp"}, {"file": "b.h"}]})
    result_line = {"message": {"content": [
        {"type": "tool_result", "tool_use_id": use_id,
         "content": [{"type": "text", "text": payload}]}]}}
    (proj / f"{session_id}.jsonl").write_text(
        json.dumps(use_line) + "\n" + json.dumps(result_line) + "\n")
    assert "find_related" not in json.dumps(result_line)  # mirror the real-transcript invariant

    monkeypatch.setattr(runner.os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    queries, files = _find_related_files_for_session(session_id)
    assert queries == ["JNI registration"]
    assert files == ["a.cpp", "b.h"]


def test_find_related_files_missing_session_returns_empty():
    assert _find_related_files_for_session("") == ([], [])
    assert _find_related_files_for_session("no-such-session-xyz") == ([], [])
