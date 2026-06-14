"""Deterministic routing eval: cues present in tool descriptions + coverage."""

import pytest

from repo_memory.routing_eval import GOLDEN, check_routing
from repo_memory.server import build_app, TOOL_NAMES


def test_check_routing_ok():
    descs = {"t": "this description mentions the blast radius clearly"}
    cases = [{"question": "q", "expected_tool": "t", "cue": "blast radius"}]
    assert check_routing(descs, cases) == []


def test_check_routing_reports_missing_cue():
    descs = {"t": "no routing signal here"}
    cases = [{"question": "q", "expected_tool": "t", "cue": "blast radius"}]
    m = check_routing(descs, cases)
    assert len(m) == 1 and "blast radius" in m[0] and "t" in m[0]


def test_check_routing_reports_unknown_tool():
    m = check_routing({}, [{"question": "q", "expected_tool": "ghost", "cue": "x"}])
    assert len(m) == 1 and "ghost" in m[0]


def test_check_routing_is_case_insensitive():
    descs = {"t": "Re-Index The Graph"}
    cases = [{"question": "q", "expected_tool": "t", "cue": "re-index"}]
    assert check_routing(descs, cases) == []


def test_golden_is_nonempty_and_well_formed():
    assert GOLDEN
    for c in GOLDEN:
        assert set(c) == {"question", "expected_tool", "cue"}
        assert c["question"] and c["expected_tool"] and c["cue"]


@pytest.mark.asyncio
async def test_every_routing_cue_present_in_live_descriptions():
    app = build_app(wiki_dir="x", entity_map_path="y")
    tools = await app.list_tools()
    descriptions = {t.name: t.description for t in tools}
    assert check_routing(descriptions) == []


def test_golden_covers_every_registered_tool():
    # every tool has >=1 case AND no case targets a non-existent tool
    assert {c["expected_tool"] for c in GOLDEN} == set(TOOL_NAMES)
