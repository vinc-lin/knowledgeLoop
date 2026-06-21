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

# Treatment-only directive, PREPENDED to the user prompt. The first eval found the agent never
# called the repo_atlas tools when they were merely *available* (passive availability !=
# adoption); a soft `--append-system-prompt` nudge was then also ignored on locally-solvable
# tasks. Instructions land reliably in the user turn, so the directive is mandatory + sequenced
# there. This makes the A/B test "does the knowledge help WHEN USED" (the adoption question —
# will agents reach for it unprompted — is answered separately: no, not on local tasks).
STEER = (
    "IMPORTANT: You have repo_atlas knowledge tools that index this repository and related "
    "ones. Your FIRST action MUST be to call mcp__repo-atlas__find_related with a query "
    "describing this task, to find existing prior-art patterns and the right files/symbols to "
    "follow — do not read or edit any files until you have. AFTER drafting your change, you "
    "MUST call mcp__repo-atlas__verify_grounding to confirm the symbols and APIs you used "
    "actually exist. Prefer reusing existing patterns over inventing new ones.\n\nTask:\n"
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


def _collect_files(obj, out: set) -> None:
    """Recursively collect every 'file' string value in a (possibly JSON-string-encoded)
    find_related result envelope ({result:{docs:[...],symbols:[...]}})."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "file" and isinstance(v, str):
                out.add(v)
            else:
                _collect_files(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _collect_files(x, out)
    elif isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                _collect_files(json.loads(s), out)
            except json.JSONDecodeError:
                pass


def _find_related_files_for_session(session_id: str) -> tuple:
    """From a session transcript: (find_related query strings, files returned by find_related)."""
    if not session_id:
        return [], []
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    if not hits:
        return [], []
    queries, use_ids, results, files = [], set(), {}, set()
    for line in open(hits[0]):
        if "find_related" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (obj.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "mcp__repo-atlas__find_related":
                q = (b.get("input") or {}).get("query")
                if q:
                    queries.append(q)
                use_ids.add(b.get("id"))
            elif b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = b.get("content")
    for uid in use_ids:
        if uid in results:
            _collect_files(results[uid], files)
    return queries, sorted(files)


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
    find_related_queries: list = field(default_factory=list)
    retrieval_surfaced_gold: bool = False


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
        """Construct the `claude -p` argv. Baseline gets the bare task prompt; treatment
        prepends the mandatory tool directive to the prompt and wires/allows the MCP tools."""
        prompt = self._steer + task.prompt if condition == "treatment" else task.prompt
        cmd = ["claude", "-p", prompt, "--output-format", "json",
               "--permission-mode", "acceptEdits", "--add-dir", work, "--model", self._model]
        if condition == "treatment":
            cmd += ["--mcp-config", self._mcp, "--strict-mcp-config",
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
        queries, surfaced = [], False
        if condition == "treatment":
            queries, fr_files = _find_related_files_for_session(session_id)
            surfaced = any(pf in set(fr_files) for pf in task.prior_art_files)
        return RunResult(condition, symbols, files, tool_calls, tokens, raw, diff, atlas_calls,
                         find_related_queries=queries, retrieval_surfaced_gold=surfaced)
