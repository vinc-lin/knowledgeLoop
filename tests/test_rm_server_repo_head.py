"""Unit tests for server._resolve_repo_head (the freshness anchor wiring).

The standalone MCP launch (`python -m repo_memory.server`) must populate
AppState.repo_head, otherwise compute_freshness caps at 'unverified' and
assess_impact stays permanently blocked. main() derives it via this helper.
"""

import os
import shutil
import subprocess

import pytest

from repo_memory.server import _resolve_repo_head

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_env_override_wins():
    head = _resolve_repo_head("/anywhere", {"REPO_MEMORY_REPO_HEAD": "deadbeef"})
    assert head == "deadbeef"


def test_derives_head_from_git_repo():
    if shutil.which("git") is None:
        pytest.skip("git not available")
    expected = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
    ).decode().strip()
    assert _resolve_repo_head(REPO_ROOT, {}) == expected


def test_non_git_path_returns_none(tmp_path):
    assert _resolve_repo_head(str(tmp_path), {}) is None


def test_none_repo_path_returns_none():
    assert _resolve_repo_head(None, {}) is None
