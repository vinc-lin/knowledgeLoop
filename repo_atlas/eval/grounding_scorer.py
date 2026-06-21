from __future__ import annotations


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
