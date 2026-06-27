from __future__ import annotations

import glob
import os
import tomllib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    id: str
    kind: str               # 'dev' | 'bugfix'
    repo: str
    prompt: str
    rubric: str
    expected_symbols: list = field(default_factory=list)
    expected_files: list = field(default_factory=list)
    prior_art_files: list = field(default_factory=list)
    required_apis: list = field(default_factory=list)
    retrieval_query: str = ""    # focused, INTENT-only find_related query (never names required_apis)


def task_query(task) -> str:
    """The query to send to find_related for this task: the author-written focused
    `retrieval_query` when present, else the (verbose) prompt. The focused query describes the
    task INTENT and must NOT contain any required_apis token — otherwise the forced-inject arm
    and the offline proxy would be teaching-to-the-test."""
    return getattr(task, "retrieval_query", "") or task.prompt


def load_tasks(directory: str) -> list[Task]:
    tasks = []
    for path in sorted(glob.glob(os.path.join(directory, "*.toml"))):
        with open(path, "rb") as fh:
            d = tomllib.load(fh)
        tasks.append(Task(
            id=d["id"], kind=d["kind"], repo=d["repo"], prompt=d["prompt"],
            rubric=d["rubric"],
            expected_symbols=list(d.get("expected_symbols", [])),
            expected_files=list(d.get("expected_files", [])),
            prior_art_files=list(d.get("prior_art_files", [])),
            required_apis=list(d.get("required_apis", [])),
            retrieval_query=d.get("retrieval_query", "")))
    return tasks
