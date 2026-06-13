"""Path normalization + suffix matching between CodeWiki and CBM paths."""

from repo_memory.bridge.paths import normalize_path, path_suffix_match


def test_normalize_passthrough_relative():
    assert normalize_path("codewiki/cli/x.py") == "codewiki/cli/x.py"


def test_normalize_strips_repo_root():
    assert normalize_path("/home/u/repo/codewiki/x.py", "/home/u/repo") == "codewiki/x.py"


def test_normalize_backslashes_and_root():
    assert normalize_path("C:\\repo\\a.py", "C:\\repo") == "a.py"


def test_normalize_strips_leading_dot_slash():
    assert normalize_path("./a.py") == "a.py"


def test_normalize_keeps_dotfile():
    assert normalize_path(".env.py") == ".env.py"


def test_suffix_match_shared_tail():
    assert path_suffix_match("codewiki/cli/x.py", "/abs/codewiki/cli/x.py") is True


def test_suffix_match_rejects_partial_segment():
    # "config.py" must NOT match "myconfig.py"
    assert path_suffix_match("a/config.py", "b/myconfig.py") is False
