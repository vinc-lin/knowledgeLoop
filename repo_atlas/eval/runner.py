from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Protocol

from repo_atlas.eval.tasks import Task
from repo_atlas.eval.extract import extract_refs

# Treatment-only system-prompt append. The first eval found the agent NEVER called the
# repo_atlas tools when they were merely *available* (passive availability != adoption), so
# the treatment arm was behaviorally identical to baseline. This steer makes the A/B real:
# same task in both arms; treatment additionally is told the tools exist and to use them.
STEER = (
    "You have repo_atlas knowledge tools available that index this repository and related "
    "ones: mcp__repo-atlas__find_related, mcp__repo-atlas__prepare_change, and "
    "mcp__repo-atlas__verify_grounding. BEFORE writing code, call find_related (or "
    "prepare_change) to locate existing prior-art patterns and the right files/symbols to "
    "follow. AFTER drafting your change, call verify_grounding to confirm the symbols and APIs "
    "you used actually exist. Prefer reusing existing patterns over inventing new ones."
)


def _count_atlas_in_transcript(path: str) -> int:
    """Count repo_atlas MCP tool_use calls in a Claude Code session transcript (.jsonl).

    Adoption telemetry: lets the scorecard show whether the treatment agent actually invoked
    the tools, distinguishing 'tool didn't help' from 'tool was never exercised'. Missing/
    unreadable file -> 0."""
    try:
        fh = open(path)
    except OSError:
        return 0
    n = 0
    with fh:
        for line in fh:
            if "mcp__repo-atlas" not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (obj.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if (isinstance(block, dict) and block.get("type") == "tool_use"
                            and str(block.get("name", "")).startswith("mcp__repo-atlas")):
                        n += 1
    return n


def _atlas_calls_for_session(session_id: str) -> int:
    """Locate a session transcript by id under ~/.claude/projects/* and count atlas calls."""
    if not session_id:
        return 0
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    return _count_atlas_in_transcript(hits[0]) if hits else 0


@dataclass
class RunResult:
    condition: str                  # 'baseline' | 'treatment'
    referenced_symbols: list = field(default_factory=list)
    touched_files: list = field(default_factory=list)
    tool_calls: int = 0
    tokens: int = 0
    raw: dict = field(default_factory=dict)
    diff: str = ""
    atlas_calls: int = 0            # repo_atlas MCP tool calls observed in the session


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
                 model: str = "claude-sonnet-4-6", steer: str = STEER):
        self._repo_paths = repo_paths           # repo name -> source path
        self._mcp = mcp_config_path
        self._model = model
        self._steer = steer

    def _build_cmd(self, task: Task, condition: str, work: str) -> list:
        """Construct the `claude -p` argv. Both arms get the identical task prompt; the
        treatment arm additionally wires the MCP server, allows the repo_atlas tools, and
        appends the steer so the agent actually uses them."""
        cmd = ["claude", "-p", task.prompt, "--output-format", "json",
               "--permission-mode", "acceptEdits", "--add-dir", work, "--model", self._model]
        if condition == "treatment":
            cmd += ["--mcp-config", self._mcp, "--strict-mcp-config",
                    "--append-system-prompt", self._steer,
                    "--allowedTools", "mcp__repo-atlas__find_related",
                    "mcp__repo-atlas__prepare_change", "mcp__repo-atlas__verify_grounding",
                    "mcp__repo-atlas__list_repos"]
        return cmd

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

            proc = subprocess.run(self._build_cmd(task, condition, work), cwd=work,
                                  capture_output=True, text=True, timeout=900)
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
        # Adoption telemetry: count repo_atlas tool calls from the persisted session transcript.
        session_id = raw.get("session_id", "") if isinstance(raw, dict) else ""
        atlas_calls = _atlas_calls_for_session(session_id)
        return RunResult(condition, symbols, files, tool_calls, tokens, raw, diff, atlas_calls)
