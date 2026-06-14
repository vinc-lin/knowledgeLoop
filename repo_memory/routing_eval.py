"""Deterministic routing-eval harness.

GOLDEN is a living spec of intended tool routing: each case maps a representative
question to the tool that should handle it, plus a `cue` -- a phrase that must
appear in that tool's MCP description (the signal a competent LLM routes on).
check_routing() flags any tool whose description has dropped its cue, or any case
that targets a tool that doesn't exist. Pure/offline -- no LLM, no network.

Every cue is a real (case-insensitive) substring of its tool's current description.
"""

from __future__ import annotations

GOLDEN: list[dict] = [
    {"question": "What is this project's overall architecture?",
     "expected_tool": "get_repo_overview", "cue": "overall architecture"},
    {"question": "What are the module boundaries in this repo?",
     "expected_tool": "list_modules", "cue": "module boundaries"},
    {"question": "Which module handles request authentication?",
     "expected_tool": "search_wiki", "cue": "which module does"},
    {"question": "Show the doc, path, and components for the ingestion module.",
     "expected_tool": "get_module_doc", "cue": "path, and components"},
    {"question": "Which real source files implement the ingestion module?",
     "expected_tool": "get_related_files", "cue": "real source files"},
    {"question": "Find the exact symbol named ChunkStore.",
     "expected_tool": "search_code_graph", "cue": "locate exact symbols"},
    {"question": "Who calls process_order and what does it call?",
     "expected_tool": "trace_symbol", "cue": "call paths"},
    {"question": "Show the source for proj.mod.ChunkStore by its qualified name.",
     "expected_tool": "get_code_snippet", "cue": "qualified name"},
    {"question": "Give me a graph-level architecture summary with entry points.",
     "expected_tool": "get_architecture", "cue": "entry points"},
    {"question": "Explain how chunking works, with source-code proof.",
     "expected_tool": "explain_with_sources", "cue": "need proof"},
    {"question": "What is the blast radius of my current changes?",
     "expected_tool": "assess_impact", "cue": "blast radius"},
    {"question": "The graph is stale -- re-index it.",
     "expected_tool": "refresh_index", "cue": "re-index"},
]


def check_routing(descriptions: dict, cases: list = GOLDEN) -> list:
    """Return a list of mismatch messages (empty == every routing cue is present).

    A mismatch is reported when a case's expected_tool is absent from
    `descriptions`, or when its `cue` is not a (case-insensitive) substring of that
    tool's description.
    """
    mismatches: list = []
    for c in cases:
        tool = c["expected_tool"]
        if tool not in descriptions:
            mismatches.append(f"{tool}: not a registered tool (case: {c['question']!r})")
        elif c["cue"].lower() not in descriptions[tool].lower():
            mismatches.append(
                f"{tool}: routing cue {c['cue']!r} missing from description "
                f"(case: {c['question']!r})")
    return mismatches
