import json

import pytest
from repo_atlas.eval.runner import (RunResult, StubRunner, ClaudeRunner, NUDGE,
                                    _count_atlas_in_transcript, format_injection,
                                    SessionLimitReached, _is_session_limit)
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


def test_claude_runner_timeout_default_and_override():
    assert ClaudeRunner({"g": "/x"}, "/m")._timeout == 900
    assert ClaudeRunner({"g": "/x"}, "/m", timeout=300)._timeout == 300


def test_run_agent_timeout_returns_empty_not_raises():
    # a timed-out agent run must NOT raise (which would drop the whole task across all arms);
    # it returns {} so the arm is scored as a failure on its (partial/empty) diff.
    r = ClaudeRunner({"g": "/x"}, "/m", timeout=1)
    assert r._run_agent(["sleep", "5"], "/tmp") == {}


def test_run_agent_parses_json_stdout():
    r = ClaudeRunner({"g": "/x"}, "/m", timeout=10)
    assert r._run_agent(["printf", '{"session_id":"abc","num_turns":3}'], "/tmp") == {
        "session_id": "abc", "num_turns": 3}


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


def test_build_cmd_assisted_soft_nudge_wires_mcp():
    r = ClaudeRunner({"gpuimage": "/x"}, "/tmp/mcp.json")
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    cmd = r._build_cmd(t, "assisted", "/work", nudge_text=NUDGE)
    prompt = cmd[cmd.index("-p") + 1]
    assert prompt.startswith(NUDGE)                        # nudge prepended
    assert "do the thing" in prompt                        # task text preserved
    assert "MUST" not in NUDGE and "FIRST" not in NUDGE    # SOFT, not the STEER directive
    assert "find_related" in NUDGE                         # names the tool to consider
    assert "--mcp-config" in cmd                           # tools available (agent may choose)


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


@pytest.mark.asyncio
async def test_inject_text_uses_retriever_for_forced_arm():
    from repo_atlas.eval.offline.retriever import StubRetriever
    sr = StubRetriever(hits_by_query={
        "do the thing": [{"name": "cgeFoo", "file": "a.cpp", "text": "foo helper"}]})
    r = ClaudeRunner({"gpuimage": "/x"}, "/m", retriever=sr)
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="do the thing", rubric="r")
    txt = await r._inject_text(t)
    assert txt.startswith("Relevant prior art") and "cgeFoo" in txt


@pytest.mark.asyncio
async def test_inject_text_empty_without_retriever():
    r = ClaudeRunner({"gpuimage": "/x"}, "/m")             # no retriever wired
    t = Task(id="t", kind="dev", repo="gpuimage", prompt="p", rubric="r")
    assert await r._inject_text(t) == ""


class _RecordingRetriever:
    """Captures the (query, repo) of the last retrieve() call. Returns one canned hit."""
    def __init__(self):
        self.last_query = None
        self.last_repo = "UNSET"

    async def retrieve(self, query, repo, k, kinds=None):
        self.last_query, self.last_repo = query, repo
        return [{"name": "cgeFoo", "file": "a.cpp", "text": "foo helper"}]


@pytest.mark.asyncio
async def test_inject_text_uses_focused_query_and_all_repos():
    # forced-inject must retrieve cross-repo (repo=None) with the task's FOCUSED query,
    # not the verbose prompt scoped to one repo.
    rec = _RecordingRetriever()
    r = ClaudeRunner({"libxcam-ocl": "/x"}, "/m", retriever=rec)
    t = Task(id="t", kind="dev", repo="libxcam-ocl",
             prompt="long verbose multi-sentence task description",
             rubric="r", retrieval_query="cl image handler fps profiling")
    await r._inject_text(t)
    assert rec.last_query == "cl image handler fps profiling"   # focused query, not prompt
    assert rec.last_repo is None                                # all repos, not task.repo


def test_is_session_limit_matches_quota_messages():
    assert _is_session_limit("You've hit your session limit · resets 8pm (Asia/Shanghai)") is True
    assert _is_session_limit("Claude usage limit reached") is True
    assert _is_session_limit("SESSION LIMIT") is True                      # case-insensitive


def test_is_session_limit_ignores_normal_output():
    assert _is_session_limit('{"result":"done","is_error":false,"num_turns":7}') is False
    assert _is_session_limit("I changed the buffer rate of the encoder.") is False
    assert _is_session_limit("") is False
    assert _is_session_limit(None) is False                                # tolerates None


def test_run_agent_raises_on_session_limit():
    # claude prints the limit text instead of a JSON envelope -> must raise (abort), not return {}
    r = ClaudeRunner({"g": "/x"}, "/m", timeout=10)
    with pytest.raises(SessionLimitReached):
        r._run_agent(["printf", "You have hit your session limit; resets 8pm"], "/tmp")
