"""resolve_project matches list_projects by root_path; ensure_project caches on state."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.state import AppState
from repo_memory.graph.client import CBMUnavailable
from repo_memory.graph.project import resolve_project, ensure_project


def _client(ret):
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value=ret)
    return c


@pytest.mark.asyncio
async def test_resolve_matches_root_path(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    c = _client({"projects": [
        {"name": "other", "root_path": "/somewhere/else"},
        {"name": "the-proj", "root_path": str(repo)}]})
    assert await resolve_project(c, str(repo)) == "the-proj"


@pytest.mark.asyncio
async def test_resolve_none_when_not_indexed(tmp_path):
    c = _client({"projects": [{"name": "x", "root_path": "/other"}]})
    assert await resolve_project(c, str(tmp_path)) is None


@pytest.mark.asyncio
async def test_resolve_none_on_empty_repo_path():
    c = _client({"projects": []})
    assert await resolve_project(c, None) is None


@pytest.mark.asyncio
async def test_resolve_none_on_cbm_unavailable(tmp_path):
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(side_effect=CBMUnavailable("down"))
    assert await resolve_project(c, str(tmp_path)) is None


@pytest.mark.asyncio
async def test_ensure_project_resolves_and_caches(tmp_path):
    repo = tmp_path / "p"
    repo.mkdir()
    c = _client({"projects": [{"name": "P", "root_path": str(repo)}]})
    st = AppState(wiki_dir="w", entity_map_path="e", repo_path=str(repo), cbm=c)
    assert await ensure_project(st) == "P"
    assert st.project == "P"
    c.call_tool_with_restart.reset_mock()
    assert await ensure_project(st) == "P"          # second call hits the cache
    c.call_tool_with_restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_project_none_without_cbm_or_repo():
    no_cbm = AppState(wiki_dir="w", entity_map_path="e", repo_path="/r", cbm=None)
    assert await ensure_project(no_cbm) is None
    no_repo = AppState(wiki_dir="w", entity_map_path="e", cbm=object())
    assert await ensure_project(no_repo) is None
