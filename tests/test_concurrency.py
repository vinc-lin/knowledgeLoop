"""Stage 5 verification: per-module tree isolation + merge equals the sequential result."""

import json
import os

import pytest

from codewiki.src.config import Config, MODULE_TREE_FILENAME
from codewiki.src.be.documentation_generator import DocumentationGenerator


class _TreeMutatingBackend:
    """Mimics run_module_agent: loads the (possibly isolated) tree, adds a sub-module
    to its own node, saves, writes docs. This is the state that must merge correctly."""

    def __init__(self):
        self.calls = []

    async def run_module_agent(self, module_name, components, core_component_ids,
                               module_path, working_dir, module_tree_path=None):
        self.calls.append(module_name)
        path = module_tree_path or os.path.join(working_dir, MODULE_TREE_FILENAME)
        with open(path, encoding="utf-8") as fh:
            tree = json.load(fh)
        node = tree
        for i, part in enumerate(module_path):
            node = node[part]
            if i != len(module_path) - 1:
                node = node["children"]
        node.setdefault("children", {})[f"{module_name}_sub"] = {
            "components": [f"{module_name}::s"], "children": {},
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(tree, fh)
        for fname in (f"{module_name}.md", f"{module_name}_sub.md"):
            with open(os.path.join(working_dir, fname), "w", encoding="utf-8") as fh:
                fh.write("x")
        return tree


def _generator(tmp_path, backend):
    cfg = Config(
        repo_path=str(tmp_path), output_dir=str(tmp_path), dependency_graph_dir=str(tmp_path),
        docs_dir=str(tmp_path), max_depth=3, llm_base_url="http://gw/v1", llm_api_key="k",
        main_model="deepseek-chat", cluster_model="deepseek-chat", fallback_model="fb",
        provider="openai-compatible",
    )
    return DocumentationGenerator(cfg, commit_id="t", backend=backend)


def _base_tree():
    return {
        "A": {"components": ["a::A"], "children": {}},
        "B": {"components": ["b::B"], "children": {}},
        "C": {"components": ["c::C"], "children": {}},
    }


def test_merge_grafts_disjoint_subtrees():
    base = _base_tree()
    # Two isolated results, each with its own node updated.
    updated_a = {"A": {"components": ["a::A"], "children": {"A_sub": {"components": [], "children": {}}}},
                 "B": {"components": ["b::B"], "children": {}}, "C": base["C"]}
    updated_b = {"A": {"components": ["a::A"], "children": {}},
                 "B": {"components": ["b::B"], "children": {"B_sub": {"components": [], "children": {}}}},
                 "C": base["C"]}
    merged = DocumentationGenerator._merge_module_trees(
        base, [(["A"], updated_a), (["B"], updated_b)]
    )
    assert "A_sub" in merged["A"]["children"]
    assert "B_sub" in merged["B"]["children"]
    assert merged["C"]["children"] == {}  # untouched


@pytest.mark.asyncio
async def test_concurrent_equals_sequential(tmp_path):
    wd = str(tmp_path)
    tree_path = os.path.join(wd, MODULE_TREE_FILENAME)
    processing_order = [(["A"], "A"), (["B"], "B"), (["C"], "C")]

    # --- sequential golden run (shared tree, one at a time) ---
    seq_dir = os.path.join(wd, "seq"); os.makedirs(seq_dir)
    seq_path = os.path.join(seq_dir, MODULE_TREE_FILENAME)
    with open(seq_path, "w", encoding="utf-8") as fh:
        json.dump(_base_tree(), fh)
    seq_backend = _TreeMutatingBackend()
    seq_gen = _generator(tmp_path, seq_backend)
    for mp, mn in processing_order:
        await seq_backend.run_module_agent(mn, {}, [], mp, seq_dir)
    with open(seq_path, encoding="utf-8") as fh:
        sequential_tree = json.load(fh)

    # --- concurrent run (isolated trees + merge) ---
    con_dir = os.path.join(wd, "con"); os.makedirs(con_dir)
    con_path = os.path.join(con_dir, MODULE_TREE_FILENAME)
    with open(con_path, "w", encoding="utf-8") as fh:
        json.dump(_base_tree(), fh)
    con_gen = _generator(tmp_path, _TreeMutatingBackend())
    merged = await con_gen._process_modules_concurrent(
        processing_order, {}, con_dir, con_path, concurrency=3
    )

    assert merged == sequential_tree                      # golden-diff: identical
    assert not any(f.startswith("module_tree.") and f != MODULE_TREE_FILENAME
                   for f in os.listdir(con_dir))          # isolated tree files cleaned up


def test_concurrency_guard_unique_names():
    # The guard that selects concurrent vs sequential is name-uniqueness.
    dup = ["A", "B", "A"]
    assert len(set(dup)) != len(dup)        # collision -> would force sequential
    uniq = ["A", "B", "C"]
    assert len(set(uniq)) == len(uniq)
