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
        await client.call_tool("index_repository", {"path": REPO_ROOT})
        nodes = await enumerate_nodes_for_files(
            client, ["codewiki/cli/models/config.py"])
        names = {n.name for n in nodes}
        assert "Configuration" in names  # known codewiki class is grounded
    finally:
        await client.aclose()
