"""_resolve_commit_id returns the repo HEAD sha, or None off a git repo."""

import os
import re

from codewiki.cli.adapters.doc_generator import _resolve_commit_id

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_returns_sha_for_real_repo():
    sha = _resolve_commit_id(REPO_ROOT)
    assert sha is not None
    assert re.fullmatch(r"[0-9a-f]{40}", sha)


def test_returns_none_for_non_git_dir(tmp_path):
    assert _resolve_commit_id(str(tmp_path)) is None
