"""Stage 4 verification: the missing-doc walker/sweep regenerates exactly the absent nodes."""

import json
import os

import pytest

from codewiki.src.config import Config
from codewiki.src.be.documentation_generator import DocumentationGenerator
from codewiki.src.config import MODULE_TREE_FILENAME


class _FakeBackend:
    """Records run_module_agent calls and writes a stub doc (simulates a successful regen)."""

    def __init__(self, working_dir):
        self.working_dir = working_dir
        self.calls = []

    async def run_module_agent(self, module_name, components, core_component_ids, module_path, working_dir):
        self.calls.append(module_name)
        with open(os.path.join(working_dir, f"{module_name}.md"), "w", encoding="utf-8") as fh:
            fh.write(f"# {module_name}\n")
        return {}


def _generator(tmp_path, backend):
    cfg = Config(
        repo_path=str(tmp_path), output_dir=str(tmp_path), dependency_graph_dir=str(tmp_path),
        docs_dir=str(tmp_path), max_depth=3, llm_base_url="http://gw/v1", llm_api_key="k",
        main_model="deepseek-chat", cluster_model="deepseek-chat", fallback_model="fb",
        provider="openai-compatible",
    )
    return DocumentationGenerator(cfg, commit_id="t", backend=backend)


def _tree():
    return {
        "foundation": {
            "components": ["a::A"],
            "children": {
                "compat": {"components": ["b::B"], "children": {}},
                "mem": {"components": ["c::C"], "children": {}},
            },
        }
    }


def test_iter_tree_nodes_yields_all(tmp_path):
    gen = _generator(tmp_path, _FakeBackend(str(tmp_path)))
    names = sorted(n for _, n, _ in gen._iter_tree_nodes(_tree()))
    assert names == ["compat", "foundation", "mem"]


@pytest.mark.asyncio
async def test_sweep_regenerates_only_missing(tmp_path):
    wd = str(tmp_path)
    backend = _FakeBackend(wd)
    gen = _generator(tmp_path, backend)

    tree_path = os.path.join(wd, MODULE_TREE_FILENAME)
    with open(tree_path, "w", encoding="utf-8") as fh:
        json.dump(_tree(), fh)
    # Present: foundation + compat (sanitized variant). Absent: mem.
    for name in ("foundation", "compat"):
        with open(os.path.join(wd, f"{name}.md"), "w", encoding="utf-8") as fh:
            fh.write("x")

    await gen._fill_missing_docs(components={}, working_dir=wd, module_tree_path=tree_path)

    assert backend.calls == ["mem"]
    assert os.path.exists(os.path.join(wd, "mem.md"))


@pytest.mark.asyncio
async def test_sweep_noop_when_all_present(tmp_path):
    wd = str(tmp_path)
    backend = _FakeBackend(wd)
    gen = _generator(tmp_path, backend)
    tree_path = os.path.join(wd, MODULE_TREE_FILENAME)
    with open(tree_path, "w", encoding="utf-8") as fh:
        json.dump(_tree(), fh)
    for name in ("foundation", "compat", "mem"):
        with open(os.path.join(wd, f"{name}.md"), "w", encoding="utf-8") as fh:
            fh.write("x")

    await gen._fill_missing_docs(components={}, working_dir=wd, module_tree_path=tree_path)
    assert backend.calls == []
