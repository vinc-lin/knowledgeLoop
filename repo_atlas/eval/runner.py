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

INJECT_HEADER = "Relevant prior art in this codebase (reuse these instead of inventing):"


def format_injection(units: list, *, max_k: int = 5, max_chars: int = 400) -> str:
    """Render the top retrieval units as a prior-art block to PREPEND for the forced-inject arm.
    `units` are find_related_units dicts (file/name/text). Whitespace is collapsed and each
    snippet char-capped so the injected context stays bounded. Empty units -> "" (no header)."""
    rows = []
    for u in units[:max_k]:
        name = u.get("name") or u.get("qualified_name") or "?"
        path = u.get("file") or "?"
        snippet = " ".join((u.get("text") or "").split())[:max_chars]
        rows.append(f"- `{name}` ({path}): {snippet}")
    if not rows:
        return ""
    return INJECT_HEADER + "\n" + "\n".join(rows) + "\n\n"


# arm -> (wire_mcp, prompt_mode). prompt_mode: "bare" | "steer" | "inject".
# control/optional/forced-inject/mandatory-call are the canonical arms; baseline/treatment are
# retained as back-compat aliases for the legacy 2-condition harness + tests.
ARMS = {
    "control": (False, "bare"),
    "optional": (True, "bare"),
    "forced-inject": (False, "inject"),
    "mandatory-call": (True, "steer"),
    "baseline": (False, "bare"),
    "treatment": (True, "steer"),
}


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
    """Recursively collect every 'file' string value in a find_related result.

    Real find_related results are a flat list — `{"result": [{..., "file": ...}]}` — and the
    tool_result `content` is double-wrapped as a list of `{"type":"text","text":"<JSON string>"}`
    blocks, so the JSON-string-in-text-block path below is load-bearing. We recurse generically,
    so this also handles the bucketed `{result:{docs:[...],symbols:[...]}}` shape."""
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


def _find_related_files_for_session(session_id: str) -> tuple[list, list]:
    """From a session transcript: (find_related query strings, files returned by find_related).

    NB: do NOT pre-filter lines on the substring "find_related" — real Claude Code transcripts
    carry the returned files in a tool_result line that references the call only via tool_use_id
    (the string "find_related" never appears on it), so such a filter drops every result and
    `files` stays empty. The per-session transcripts are small, so scanning all lines is fine."""
    if not session_id:
        return [], []
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    if not hits:
        return [], []
    try:
        fh = open(hits[0])
    except OSError:
        return [], []
    queries, use_ids, results, files = [], set(), {}, set()
    with fh:
        for line in fh:
            if '"tool_use"' not in line and '"tool_result"' not in line:
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
                if (b.get("type") == "tool_use"
                        and b.get("name") == "mcp__repo-atlas__find_related"):
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
                 model: str = "claude-sonnet-4-6", steer: str = STEER,
                 retriever=None, inject_k: int = 5):
        self._repo_paths = repo_paths           # repo name -> source path
        self._mcp = mcp_config_path
        self._model = model
        self._steer = steer
        self._retriever = retriever             # OfflineRetriever-like; used by forced-inject
        self._inject_k = inject_k

    def _build_cmd(self, task: Task, condition: str, work: str, inject_text: str = "") -> list:
        """Construct the `claude -p` argv for an arm. control/baseline: bare prompt, no MCP.
        optional: bare prompt + MCP wired. forced-inject: prior-art prepended, NO MCP.
        mandatory-call/treatment: STEER directive prepended + MCP wired."""
        wire_mcp, mode = ARMS[condition]
        if mode == "steer":
            prompt = self._steer + task.prompt
        elif mode == "inject":
            prompt = inject_text + task.prompt
        else:
            prompt = task.prompt
        cmd = ["claude", "-p", prompt, "--output-format", "json",
               "--permission-mode", "acceptEdits", "--add-dir", work, "--model", self._model]
        if wire_mcp:
            cmd += ["--mcp-config", self._mcp, "--strict-mcp-config",
                    "--allowedTools", "mcp__repo-atlas__find_related",
                    "mcp__repo-atlas__prepare_change", "mcp__repo-atlas__verify_grounding",
                    "mcp__repo-atlas__list_repos"]
        return cmd

    async def _inject_text(self, task: Task) -> str:
        """Forced-inject arm: retrieve prior art via the production path and format it. Returns
        "" when no retriever is wired (the arm then degrades to a bare-prompt control)."""
        if self._retriever is None:
            return ""
        units = await self._retriever.retrieve(task.prompt, task.repo, self._inject_k)
        return format_injection(units, max_k=self._inject_k)

    async def run(self, task: Task, *, condition: str) -> RunResult:
        src = self._repo_paths[task.repo]
        work = tempfile.mkdtemp(prefix=f"eval-{task.id}-{condition}-")
        wire_mcp, mode = ARMS[condition]
        inject = await self._inject_text(task) if mode == "inject" else ""
        try:
            # src (config) + work (mkdtemp) are trusted, not user input -> shell pipe is safe.
            subprocess.run(f"git -C {src} archive HEAD | tar -x -C {work}", shell=True, check=True)
            subprocess.run(["git", "-C", work, "init", "-q"], check=True)
            subprocess.run(["git", "-C", work, "add", "-A"], check=True)
            subprocess.run(["git", "-C", work, "-c", "user.email=e@x", "-c", "user.name=e",
                            "commit", "-qm", "base"], check=True)

            proc = subprocess.run(self._build_cmd(task, condition, work, inject), cwd=work,
                                  capture_output=True, text=True, timeout=900)
            raw = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
            # NOTE: agent-driven `git commit` inside the run would evade this working-tree diff.
            diff = subprocess.run(["git", "-C", work, "diff", "HEAD"],
                                  capture_output=True, text=True).stdout
        finally:
            shutil.rmtree(work, ignore_errors=True)
        gold = list(task.required_apis) + list(task.expected_symbols)
        symbols, files = extract_refs(diff, gold_tokens=gold)
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        tokens = int(usage.get("output_tokens", 0)) + int(usage.get("input_tokens", 0))
        tool_calls = int(raw.get("num_turns", 0)) if isinstance(raw, dict) else 0  # proxy
        # Adoption telemetry: count repo_atlas tool calls from the persisted session transcript.
        session_id = raw.get("session_id", "") if isinstance(raw, dict) else ""
        atlas_calls = _atlas_calls_for_session(session_id)
        queries, surfaced = [], False
        if wire_mcp:
            queries, fr_files = _find_related_files_for_session(session_id)
            surfaced = any(pf in set(fr_files) for pf in task.prior_art_files)
        return RunResult(condition, symbols, files, tool_calls, tokens, raw, diff, atlas_calls,
                         find_related_queries=queries, retrieval_surfaced_gold=surfaced)
