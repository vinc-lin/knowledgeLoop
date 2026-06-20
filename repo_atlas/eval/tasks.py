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


def load_tasks(directory: str) -> list[Task]:
    tasks = []
    for path in sorted(glob.glob(os.path.join(directory, "*.toml"))):
        with open(path, "rb") as fh:
            d = tomllib.load(fh)
        tasks.append(Task(
            id=d["id"], kind=d["kind"], repo=d["repo"], prompt=d["prompt"],
            rubric=d["rubric"],
            expected_symbols=list(d.get("expected_symbols", [])),
            expected_files=list(d.get("expected_files", []))))
    return tasks
