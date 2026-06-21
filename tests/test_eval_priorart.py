import tomllib  # noqa: F401
from repo_atlas.eval.tasks import Task, load_tasks


def test_task_has_prior_art_default():
    t = Task(id="t", kind="dev", repo="r", prompt="p", rubric="x")
    assert t.prior_art_files == []


def test_load_tasks_reads_prior_art(tmp_path):
    (tmp_path / "a.toml").write_text(
        'id="t1"\nkind="dev"\nrepo="r"\nprompt="p"\nrubric="x"\n'
        'prior_art_files=["src/foo.h","src/foo.cpp"]\n')
    t = load_tasks(str(tmp_path))[0]
    assert t.prior_art_files == ["src/foo.h", "src/foo.cpp"]
