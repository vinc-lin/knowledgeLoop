from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Protocol

from repo_atlas.eval.tasks import Task
from repo_atlas.eval.extract import extract_refs


@dataclass
class RunResult:
    condition: str                  # 'baseline' | 'treatment'
    referenced_symbols: list = field(default_factory=list)
    touched_files: list = field(default_factory=list)
    tool_calls: int = 0
    tokens: int = 0
    raw: dict = field(default_factory=dict)
    diff: str = ""


class AgentRunner(Protocol):
    async def run(self, task: Task, *, condition: str) -> RunResult: ...


class StubRunner:
    """Returns canned RunResults keyed by (task_id, condition). For tests."""
    def __init__(self, canned: dict):
        self._canned = canned

    async def run(self, task: Task, *, condition: str) -> RunResult:
        return self._canned[(task.id, condition)]


class ClaudeRunner:
    """Drives `claude -p` headless in an isolated copy of the repo, with/without repo_atlas.

    Integration-only (needs the `claude` CLI). The repo is snapshotted at HEAD into a fresh
    git repo so the agent's change can be captured as a diff.
    """
    def __init__(self, repo_paths: dict, mcp_config_path: str,
                 model: str = "claude-sonnet-4-6"):
        self._repo_paths = repo_paths           # repo name -> source path
        self._mcp = mcp_config_path
        self._model = model

    async def run(self, task: Task, *, condition: str) -> RunResult:
        src = self._repo_paths[task.repo]
        work = tempfile.mkdtemp(prefix=f"eval-{task.id}-{condition}-")
        try:
            # src (config) + work (mkdtemp) are trusted, not user input -> shell pipe is safe.
            subprocess.run(f"git -C {src} archive HEAD | tar -x -C {work}", shell=True, check=True)
            subprocess.run(["git", "-C", work, "init", "-q"], check=True)
            subprocess.run(["git", "-C", work, "add", "-A"], check=True)
            subprocess.run(["git", "-C", work, "-c", "user.email=e@x", "-c", "user.name=e",
                            "commit", "-qm", "base"], check=True)

            cmd = ["claude", "-p", task.prompt, "--output-format", "json",
                   "--permission-mode", "acceptEdits", "--add-dir", work, "--model", self._model]
            if condition == "treatment":
                cmd += ["--mcp-config", self._mcp, "--strict-mcp-config",
                        "--allowedTools", "mcp__repo-atlas__find_related",
                        "mcp__repo-atlas__prepare_change", "mcp__repo-atlas__verify_grounding"]
            proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=900)
            raw = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
            # NOTE: agent-driven `git commit` inside the run would evade this working-tree diff.
            diff = subprocess.run(["git", "-C", work, "diff", "HEAD"],
                                  capture_output=True, text=True).stdout
        finally:
            shutil.rmtree(work, ignore_errors=True)
        symbols, files = extract_refs(diff)
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        tokens = int(usage.get("output_tokens", 0)) + int(usage.get("input_tokens", 0))
        tool_calls = int(raw.get("num_turns", 0)) if isinstance(raw, dict) else 0  # proxy
        return RunResult(condition, symbols, files, tool_calls, tokens, raw, diff)
