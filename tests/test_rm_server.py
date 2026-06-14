"""The facade registers all 11 tools with non-empty descriptions."""

import pytest

from repo_memory.server import build_app, TOOL_NAMES


@pytest.mark.asyncio
async def test_registers_eleven_named_tools():
    app = build_app(wiki_dir="w", entity_map_path="e", repo_head="r")
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert names == set(TOOL_NAMES)
    assert len(TOOL_NAMES) == 11
    for t in tools:
        assert t.description and len(t.description) > 20  # routing-aware descriptions
