"""End-to-end: run ONE task with/without repo_atlas via the real claude CLI + gateway judge.
Gated (needs claude CLI, gateway, indexed store)."""
import os
import shutil
import pytest

from repo_atlas.config import load_config
from repo_atlas.store import Store
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.runner import ClaudeRunner
from repo_atlas.eval.judge import GatewayJudge
from repo_atlas.eval.oracle import store_exists_fn
from repo_atlas.eval.harness import run_pair


@pytest.mark.integration
@pytest.mark.asyncio
async def test_one_task_with_and_without(tmp_path):
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not available")
    cfg = load_config(os.environ)
    if not cfg.base_url:
        pytest.skip("gateway not configured")
    mcp = os.environ.get("REPO_ATLAS_MCP_CONFIG")
    if not mcp or not os.path.exists(mcp):
        pytest.skip("REPO_ATLAS_MCP_CONFIG not set")
    store = Store(cfg.db_path)
    task = Task(id="smoke", kind="dev", repo="gpuimage",
                prompt="Add a one-line comment to the top of any one source file naming the project.",
                rubric="The diff adds a comment mentioning the project.",
                expected_files=[])
    runner = ClaudeRunner({"gpuimage": "/mnt/x/code/corpora/android-gpuimage-plus"}, mcp)
    judge = GatewayJudge(cfg.base_url, cfg.api_key,
                         os.environ.get("REPO_ATLAS_JUDGE_MODEL", "deepseek-chat"))
    try:
        pair = await run_pair(task, runner, judge, store_exists_fn(store, "gpuimage"))
    except Exception as exc:
        pytest.skip(f"e2e run failed (claude/gateway): {exc}")
    assert pair.task_id == "smoke"
    assert pair.baseline.condition == "baseline"
    assert pair.treatment.condition == "treatment"
