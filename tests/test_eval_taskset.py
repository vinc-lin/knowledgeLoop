import os

from repo_atlas.eval.tasks import load_tasks

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKDIR = os.path.join(HERE, "repo_atlas", "eval", "tasks")


def test_starter_tasks_load_and_are_valid():
    tasks = load_tasks(TASKDIR)
    assert len(tasks) >= 6
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids))                    # unique ids
    kinds = {t.kind for t in tasks}
    assert kinds == {"dev", "bugfix"}                   # both kinds present
    for t in tasks:
        assert t.kind in ("dev", "bugfix")
        assert t.prompt and t.rubric
        assert t.expected_symbols or t.expected_files   # every task has a ground-truth key
