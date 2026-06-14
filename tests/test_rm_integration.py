"""End-to-end against a real CBM via uvx. Gated: needs network + uvx.

Run explicitly with:  .venv/bin/python -m pytest tests/test_rm_integration.py -m integration
"""

import os
import shutil
import subprocess
import pytest

from repo_memory.graph.client import CBMClient
from repo_memory.graph.nodes import enumerate_nodes_for_files

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _repo_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cbm_roundtrip_and_enumeration():
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    client = CBMClient()
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"CBM unavailable: {exc}")
    try:
        # index this repo, then enumerate nodes for a known codewiki file
        idx = await client.call_tool("index_repository", {"repo_path": REPO_ROOT})
        nodes = await enumerate_nodes_for_files(
            client, ["codewiki/cli/models/config.py"], project=idx["project"])
        names = {n.name for n in nodes}
        assert "Configuration" in names  # known codewiki class is grounded
    finally:
        await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assess_impact_blocks_when_graph_absent():
    """With no built entity_map (graph not current), assess_impact must fail closed."""
    import shutil
    from repo_memory.state import AppState
    from repo_memory.graph.client import CBMClient
    from repo_memory.tools.hybrid_tools import assess_impact
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    client = CBMClient()
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"CBM unavailable: {exc}")
    try:
        # repo_head set but no entity_map -> graph_is_current False -> blocked
        st = AppState(wiki_dir="docs", entity_map_path="missing.json",
                      repo_head=_repo_head(), cbm=client, entity_map=None)
        e = await assess_impact(st)
        assert e["result"] is None
        assert any("unverified" in w or "stale-graph" in w for w in e["warnings"])
    finally:
        await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_then_assess_impact_is_current(tmp_path):
    """Real refresh re-indexes + rebuilds so the graph is current."""
    from repo_memory.state import AppState
    from repo_memory.wiki.loader import load_wiki
    from repo_memory.refresh import refresh
    from repo_memory.grounding import graph_is_current
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    client = CBMClient()
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"CBM unavailable: {exc}")
    try:
        wiki = load_wiki("docs")
        st = AppState(wiki_dir="docs", entity_map_path=str(tmp_path / "em.json"),
                      repo_head=_repo_head(), repo_path=REPO_ROOT, cbm=client, wiki=wiki)
        e = await refresh(st)
        assert e["result"]["reindexed"] is True
        assert graph_is_current(st)            # graph_commit now == repo_head
    finally:
        await client.aclose()
