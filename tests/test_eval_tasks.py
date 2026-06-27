from repo_atlas.eval.tasks import Task, load_tasks, task_query


def test_load_tasks(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    (d / "t1.toml").write_text(
        'id = "add-sepia"\n'
        'kind = "dev"\n'
        'repo = "gpuimage"\n'
        'prompt = "Add a sepia filter."\n'
        'expected_symbols = ["cgeImageFilter"]\n'
        'expected_files = ["library/src/main/jni/cge/common/cgeImageFilter.h"]\n'
        'rubric = "A correct solution subclasses cgeImageFilter."\n')
    tasks = load_tasks(str(d))
    assert len(tasks) == 1
    t = tasks[0]
    assert isinstance(t, Task)
    assert t.id == "add-sepia" and t.kind == "dev" and t.repo == "gpuimage"
    assert t.expected_symbols == ["cgeImageFilter"]
    assert "sepia" in t.prompt.lower()
    assert t.retrieval_query == ""              # absent -> default blank


def test_load_tasks_reads_retrieval_query(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    (d / "t1.toml").write_text(
        'id = "x"\nkind = "dev"\nrepo = "r"\nprompt = "long verbose prompt"\n'
        'rubric = "x"\nretrieval_query = "focused intent query"\n')
    t = load_tasks(str(d))[0]
    assert t.retrieval_query == "focused intent query"


def test_task_query_prefers_retrieval_query():
    t = Task(id="x", kind="dev", repo="r", prompt="verbose multi-sentence prompt",
             rubric="x", retrieval_query="focused intent")
    assert task_query(t) == "focused intent"


def test_task_query_falls_back_to_prompt():
    t = Task(id="x", kind="dev", repo="r", prompt="the prompt", rubric="x")
    assert task_query(t) == "the prompt"
    # blank retrieval_query also falls back
    t2 = Task(id="x", kind="dev", repo="r", prompt="the prompt", rubric="x", retrieval_query="")
    assert task_query(t2) == "the prompt"
