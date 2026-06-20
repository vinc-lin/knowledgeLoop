import pytest
from repo_memory.graph.nodes import enumerate_all_nodes


class FakeClient:
    """Returns 2 pages then empty; mimics CBM search_graph paging."""
    def __init__(self):
        self.calls = []

    async def call_tool_with_restart(self, name, args):
        self.calls.append((name, dict(args)))
        offset = args["offset"]
        if offset == 0:
            return {"results": [{"qualified_name": "a.f", "name": "f"},
                                {"qualified_name": "a.g", "name": "g"}], "has_more": True}
        if offset == 2:
            return {"results": [{"qualified_name": "a.g", "name": "g"}], "has_more": False}
        return {"results": []}


@pytest.mark.asyncio
async def test_enumerate_all_nodes_paginates_and_dedupes():
    client = FakeClient()
    rows = await enumerate_all_nodes(client, project="P", page_size=2)
    qns = sorted(r["qualified_name"] for r in rows)
    assert qns == ["a.f", "a.g"]            # deduped (a.g appeared twice)
    assert client.calls[0][1]["project"] == "P"
