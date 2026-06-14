"""Offline build: enumerate nodes per module -> build_entity_map -> entity_map.json."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.wiki.loader import WikiData
from repo_memory.bridge.schema import load_entity_map
from repo_memory.entity_map_build import build_and_save


@pytest.mark.asyncio
async def test_build_and_save_grounds_known_symbol(tmp_path):
    wiki = WikiData(
        module_tree={"ingestion": {"path": "src/ingest",
                     "components": ["src/ingest/pipeline.py::Pipeline"], "children": {}}},
        metadata={}, docs={}, wiki_commit="wsha", files_generated=[],
    )
    client = AsyncMock()
    client.call_tool_with_restart = AsyncMock(return_value={"results": [
        {"name": "Pipeline", "qualified_name": "src.ingest.Pipeline",
         "file_path": "src/ingest/pipeline.py", "start_line": 1, "end_line": 20}]})
    out = tmp_path / "entity_map.json"
    em = await build_and_save(wiki, client, str(out), repo_head="rsha")
    assert out.exists()
    saved = load_entity_map(str(out))
    assert saved.built_at_repo_head == "rsha"
    assert saved.wiki_commit == "wsha"
    entry = saved.modules[0].entries[0]
    assert entry.match_strategy in ("exact", "qualified_suffix")
    assert entry.cbm_node_id == "src.ingest.Pipeline"
    assert em == saved
