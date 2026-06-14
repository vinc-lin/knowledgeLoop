"""Tests for reconcile_leaf_nodes — salvaging LLM-corrupted clustering ids.

The cluster LLM frequently fails to transcribe component ids verbatim: it
collapses ``path::symbol`` to a bare ``path`` (dropping the symbol) or
fabricates a plausible ``::symbol`` suffix.  The historic exact-match filter
dropped these silently, losing real components (e.g. native JNI functions) from
the module tree.  ``reconcile_leaf_nodes`` recovers them by file path.

Real corruption observed on the ndk-samples corpus (deepseek-chat cluster model):
  parser produced  vectorization/src/main/cpp/benchmark.cpp::BenchmarkMatrixMultiplication
  LLM emitted      vectorization/src/main/cpp/benchmark.cpp        (bare, symbol dropped)
  parser produced  unit-test/app/src/main/cpp/adder_test.cpp::TEST
  LLM emitted      unit-test/app/src/main/cpp/adder_test.cpp::adder_test  (fabricated symbol)
"""

import types

from codewiki.src.be.cluster_modules import (
    cluster_modules,
    format_potential_core_components,
    reconcile_leaf_nodes,
)
from codewiki.src.be.dependency_analyzer.models.core import Node


def _node(component_id: str, code: str = "") -> Node:
    """Minimal Node for a given component id (``relative_path::symbol``)."""
    relative_path = component_id.split("::")[0]
    name = component_id.split("::", 1)[1] if "::" in component_id else component_id
    return Node(
        id=component_id,
        name=name,
        component_type="function",
        file_path=relative_path,
        relative_path=relative_path,
        source_code=code,
    )


def _components(*ids: str) -> dict:
    return {cid: _node(cid) for cid in ids}


def test_bare_path_expands_to_all_file_components():
    """A bare file path (dropped symbol) recovers every component in that file."""
    components = _components(
        "vectorization/src/main/cpp/benchmark.cpp::Benchmark",
        "vectorization/src/main/cpp/benchmark.cpp::BenchmarkMatrixMultiplication",
    )
    resolved, unresolved = reconcile_leaf_nodes(
        ["vectorization/src/main/cpp/benchmark.cpp"], components
    )
    assert resolved == [
        "vectorization/src/main/cpp/benchmark.cpp::Benchmark",
        "vectorization/src/main/cpp/benchmark.cpp::BenchmarkMatrixMultiplication",
    ]
    assert unresolved == []


def test_fabricated_symbol_recovered_by_file_path():
    """A wrong/fabricated ``::symbol`` maps back via its (correct) file path."""
    components = _components("unit-test/app/src/main/cpp/adder_test.cpp::TEST")
    resolved, unresolved = reconcile_leaf_nodes(
        ["unit-test/app/src/main/cpp/adder_test.cpp::adder_test"], components
    )
    assert resolved == ["unit-test/app/src/main/cpp/adder_test.cpp::TEST"]
    assert unresolved == []


def test_valid_identifier_kept_unchanged():
    """An identifier that already matches a component key is preserved as-is."""
    components = _components("unit-test/app/src/main/cpp/adder.cpp::add")
    resolved, unresolved = reconcile_leaf_nodes(
        ["unit-test/app/src/main/cpp/adder.cpp::add"], components
    )
    assert resolved == ["unit-test/app/src/main/cpp/adder.cpp::add"]
    assert unresolved == []


def test_file_without_components_is_unresolved():
    """Genuinely empty files (header decls, unparsed CMake/GLSL) stay dropped."""
    components = _components("unit-test/app/src/main/cpp/adder.cpp::add")
    resolved, unresolved = reconcile_leaf_nodes(
        [
            "unit-test/app/src/main/cpp/adder.h::add",          # header: decl only, no component
            "unit-test/app/src/main/cpp/CMakeLists.txt::cmake",  # not a parsed language
        ],
        components,
    )
    assert resolved == []
    assert unresolved == [
        "unit-test/app/src/main/cpp/adder.h::add",
        "unit-test/app/src/main/cpp/CMakeLists.txt::cmake",
    ]


def test_no_duplicate_when_valid_and_bare_both_present():
    """Bare-path expansion does not re-add a component already listed validly."""
    components = _components("v/b.cpp::Foo")
    resolved, unresolved = reconcile_leaf_nodes(["v/b.cpp::Foo", "v/b.cpp"], components)
    assert resolved == ["v/b.cpp::Foo"]
    assert unresolved == []


# --- integration: reconciliation wired into the clustering flow -----------------


def test_format_recovers_bare_path_into_prompt_with_source():
    """The clustering prompt includes a bare-path file's recovered component + code."""
    components = {"v/b.cpp::Foo": _node("v/b.cpp::Foo", code="int Foo(){return 1;}")}
    plain, with_code = format_potential_core_components(["v/b.cpp"], components)
    assert "v/b.cpp::Foo" in plain           # recovered, not silently dropped
    assert "int Foo(){return 1;}" in with_code  # its source reaches the LLM


def test_cluster_modules_writes_reconciled_components_into_tree():
    """The stored module tree (what the doc agent reads) gets valid component ids."""
    components = {
        "v/b.cpp::Foo": _node("v/b.cpp::Foo", code="int Foo(){return 1;}"),
        "v/c.cpp::Bar": _node("v/c.cpp::Bar", code="int Bar(){return 2;}"),
    }
    # LLM response collapses v/b.cpp::Foo to a bare path; v/c.cpp::Bar is faithful.
    grouped = (
        "<GROUPED_COMPONENTS>"
        "{'mod_a': {'components': ['v/b.cpp'], 'path': []}, "
        "'mod_b': {'components': ['v/c.cpp::Bar'], 'path': []}}"
        "</GROUPED_COMPONENTS>"
    )
    calls = {"n": 0}

    def completer(_prompt: str) -> str:
        calls["n"] += 1
        # First call clusters; later (recursive) calls return no tags -> stop.
        return grouped if calls["n"] == 1 else "no clustering"

    config = types.SimpleNamespace(max_token_per_module=0, cluster_model="stub")
    tree = cluster_modules(
        ["v/b.cpp::Foo", "v/c.cpp::Bar"], components, config, completer=completer
    )

    assert tree["mod_a"]["components"] == ["v/b.cpp::Foo"]  # recovered from bare path
    assert tree["mod_b"]["components"] == ["v/c.cpp::Bar"]  # faithful id untouched
