from __future__ import annotations

from typing import Protocol

from repo_atlas.eval.tasks import Task
from repo_atlas.eval.runner import RunResult


class Judge(Protocol):
    async def score(self, task: Task, run: RunResult) -> bool: ...


class StubJudge:
    """Canned success by task id. For tests."""
    def __init__(self, verdicts: dict):
        self._v = verdicts

    async def score(self, task: Task, run: RunResult) -> bool:
        return bool(self._v.get(task.id, False))


class GatewayJudge:
    """LLM judge via the gateway chat endpoint. Blinded: prompt does NOT reveal condition.

    Integration-only. Returns True iff the solution satisfies the task rubric."""
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._timeout = timeout

    async def score(self, task: Task, run: RunResult) -> bool:
        import httpx
        prompt = (
            "You are grading whether a code change satisfies a task. Answer ONLY 'PASS' or "
            "'FAIL'.\n\n"
            f"TASK: {task.prompt}\n\nRUBRIC: {task.rubric}\n\n"
            f"EXPECTED (a correct solution typically touches these): "
            f"symbols={task.expected_symbols} files={task.expected_files}\n\n"
            f"CANDIDATE DIFF:\n{run.diff[:6000]}\n\nVerdict:")
        resp = httpx.post(self._url, headers={"Authorization": f"Bearer {self._key}"},
                          json={"model": self._model, "temperature": 0,
                                "messages": [{"role": "user", "content": prompt}]},
                          timeout=self._timeout)
        resp.raise_for_status()
        try:                                  # tolerate a malformed/error 200 payload
            text = resp.json()["choices"][0]["message"]["content"].strip().upper()
        except (KeyError, IndexError, TypeError):
            return False
        return text.startswith("PASS")
