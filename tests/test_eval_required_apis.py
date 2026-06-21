from repo_atlas.eval.tasks import Task, load_tasks


def test_required_apis_default():
    assert Task(id="t", kind="dev", repo="r", prompt="p", rubric="x").required_apis == []


def test_load_reads_required_apis(tmp_path):
    (tmp_path / "a.toml").write_text(
        'id="t1"\nkind="dev"\nrepo="r"\nprompt="p"\nrubric="x"\n'
        'required_apis=["cgeFooBar"]\nprior_art_files=["src/a.cpp"]\n')
    t = load_tasks(str(tmp_path))[0]
    assert t.required_apis == ["cgeFooBar"] and t.prior_art_files == ["src/a.cpp"]
