import json

import pytest
from repo_atlas.eval.runner import (RunResult, StubRunner, ClaudeRunner,
                                    _count_atlas_in_transcript, format_injection)
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


def test_build_cmd_optional_wires_mcp_without_directive():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    cmd = r._build_cmd(t, "optional", "/work")
    prompt = cmd[cmd.index("-p") + 1]
    assert prompt == "do the thing"                       # NO directive prepended
    assert "find_related" not in prompt
    assert "--mcp-config" in cmd                          # tools available, agent may choose


def test_build_cmd_forced_inject_prepends_text_no_mcp():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    cmd = r._build_cmd(t, "forced-inject", "/work", inject_text="PRIOR ART: cgeFoo\n\n")
    prompt = cmd[cmd.index("-p") + 1]
    assert prompt.startswith("PRIOR ART: cgeFoo")
    assert "do the thing" in prompt
    assert "--mcp-config" not in cmd                      # knowledge injected; tools NOT wired


def test_build_cmd_control_is_bare_no_mcp():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    cmd = r._build_cmd(t, "control", "/work")
    assert cmd[cmd.index("-p") + 1] == "do the thing"
    assert "--mcp-config" not in cmd


def test_format_injection_caps_and_headers():
    units = [{"name": "cgeFoo", "file": "a.cpp", "text": "x " * 500},
             {"name": "cgeBar", "file": "b.cpp", "text": "does bar"}]
    out = format_injection(units, max_k=1, max_chars=20)
    assert out.startswith("Relevant prior art")
    assert "cgeFoo" in out and "cgeBar" not in out        # max_k=1 keeps only the top unit
    assert "x x x x x" in out and len(out) < 120          # snippet collapsed + char-capped


def test_format_injection_empty_is_blank():
    assert format_injection([]) == ""
