from __future__ import annotations

import re


class GroundingScorer:
    """Judge replacement: success = the agent's diff references EVERY required real API.

    Existence of the APIs is guaranteed at curation time (the gold-api verifier greps source),
    so the scorer only needs to confirm the agent USED them — no compiler, no LLM judge. The
    `.score(task, run)` signature matches GatewayJudge so it is a drop-in in harness._score.
    Matching is on the bare callable token the agent writes (e.g. `cgeFoo` from `cgeFoo(...)`),
    which is exactly what ClaudeRunner's extract_refs produces into run.referenced_symbols."""

    async def score(self, task, run) -> bool:
        if not task.required_apis:
            return False
        referenced = set(run.referenced_symbols)
        return all(api in referenced for api in task.required_apis)


def _added_lines_by_file(diff: str) -> dict:
    """Parse a unified diff -> {path: [added line bodies]} (the `+` lines, excluding `+++` headers)."""
    out: dict = {}
    cur = None
    for line in (diff or "").splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            out.setdefault(cur, [])
        elif cur is not None and line.startswith("+") and not line.startswith("+++"):
            out[cur].append(line[1:])
    return out


class GroundedUseScorer:
    """Judge-free scorer that fixes the lap-7 confounds, for GENUINE-GAP tasks.

    `GroundingScorer` credits a required API appearing *anywhere* in the diff — which (lap-7
    diagnosis) rewarded redundant code (an example call in a demo file, re-implementing an existing
    function) and penalised the correct "it already exists" answer. This scorer instead requires
    each required API to appear **as a call** (`api(`) on an **added line inside one of the task's
    target files** (`expected_files`). Target-site scoping kills the demo-file gaming; the call form
    requires a real use, not a mention. It is judge-free and a drop-in for harness._score.

    Pairs with genuine-gap tasks: the feature is verified-absent at a concrete site, so the correct
    solution *is* a new call there — "it already exists" is no longer a valid (uncreditable) answer.
    Falls back to whole-diff scope when a task declares no `expected_files`."""

    def __init__(self, *, require_call: bool = True):
        self._require_call = require_call

    async def score(self, task, run) -> bool:
        apis = list(task.required_apis)
        if not apis:
            return False
        by_file = _added_lines_by_file(getattr(run, "diff", "") or "")
        targets = set(task.expected_files or [])
        scoped = [ln for f, lines in by_file.items() if (not targets or f in targets) for ln in lines]
        blob = "\n".join(scoped)
        for api in apis:
            bare = api.split("::")[-1]
            pat = r"\b" + re.escape(bare) + (r"\s*\(" if self._require_call else r"\b")
            if not re.search(pat, blob):
                return False
        return True
