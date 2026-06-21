import json

import pytest
from repo_atlas.eval.runner import (RunResult, StubRunner, ClaudeRunner,
                                    _count_atlas_in_transcript)
from repo_atlas.eval.tasks import Task


def _task():
    return Task(id="t1", kind="dev", repo="gpuimage", prompt="p", rubric="r")


@pytest.mark.asyncio
async def test_stub_runner_returns_canned():
    canned = {("t1", "baseline"): RunResult("baseline", ["X"], ["a.cpp"], 9, 100, {}, ""),
              ("t1", "treatment"): RunResult("treatment", ["cgeImageFilter"], ["a.cpp"], 4, 80, {}, "")}
    r = StubRunner(canned)
    base = await r.run(_task(), condition="baseline")
    treat = await r.run(_task(), condition="treatment")
    assert base.tool_calls == 9 and treat.referenced_symbols == ["cgeImageFilter"]


def test_build_cmd_treatment_steers_and_wires_mcp():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    base = r._build_cmd(t, "baseline", "/work")
    treat = r._build_cmd(t, "treatment", "/work")
    base_prompt = base[base.index("-p") + 1]
    treat_prompt = treat[treat.index("-p") + 1]
    # baseline prompt is exactly the task; treatment PREPENDS a mandatory tool directive
    assert base_prompt == "do the thing"
    assert "do the thing" in treat_prompt                  # task text preserved
    assert "find_related" in treat_prompt and "verify_grounding" in treat_prompt
    assert "MUST" in treat_prompt                          # mandatory, not a soft nudge
    # MCP wired/allowed only in treatment
    assert "--mcp-config" not in base
    assert "--mcp-config" in treat and "--strict-mcp-config" in treat
    assert "mcp__repo-atlas__find_related" in treat


def test_count_atlas_in_transcript(tmp_path):
    rows = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__repo-atlas__find_related", "input": {}},
            {"type": "text", "text": "hi"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__repo-atlas__verify_grounding", "input": {}}]}},
    ]
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    assert _count_atlas_in_transcript(str(p)) == 2


def test_count_atlas_missing_file():
    assert _count_atlas_in_transcript("/nonexistent/x.jsonl") == 0
