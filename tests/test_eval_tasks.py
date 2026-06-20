from repo_atlas.eval.tasks import Task, load_tasks


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
