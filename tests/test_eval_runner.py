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
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do it", rubric="r")
    base = r._build_cmd(t, "baseline", "/work")
    treat = r._build_cmd(t, "treatment", "/work")
    # baseline is plain: no steer, no MCP
    assert "--append-system-prompt" not in base
    assert "--mcp-config" not in base
    # treatment steers the agent AND names the tools so it actually calls them
    assert "--append-system-prompt" in treat
    steer = treat[treat.index("--append-system-prompt") + 1]
    assert "find_related" in steer and "verify_grounding" in steer
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
