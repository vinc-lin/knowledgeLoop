"""Reactive decompose-on-overflow: profile flag, escalation decision, agent wiring."""

import json
import os

import pytest

import codewiki.src.be.pydantic_ai_backend as pab
from codewiki.src.be.agent_tools.generate_sub_module_documentations import (
    generate_sub_module_documentation_tool,
)
from codewiki.src.be.model_profiles import resolve_profile
from codewiki.src.be.pydantic_ai_backend import PydanticAIBackend
from codewiki.src.config import Config, MODULE_TREE_FILENAME
from pydantic_ai.exceptions import IncompleteToolCall


# --- Task 1: ModelProfile.decompose_on_overflow ---------------------------

def test_decompose_on_overflow_default_true():
    p = resolve_profile("openai-compatible", "deepseek-chat")
    assert p.decompose_on_overflow is True


def test_decompose_on_overflow_user_override_false():
    p = resolve_profile("openai-compatible", "deepseek-chat",
                        {"decompose_on_overflow": False})
    assert p.decompose_on_overflow is False


def test_tools_for_leaf_excludes_submodule_tool():
    tools = PydanticAIBackend._tools_for(False)
    assert generate_sub_module_documentation_tool not in tools


def test_tools_for_complex_includes_submodule_tool():
    tools = PydanticAIBackend._tools_for(True)
    assert generate_sub_module_documentation_tool in tools


def _overflow():
    return IncompleteToolCall("output limit exceeded")


def test_should_escalate_true_on_leaf_overflow_no_doc_flag_on():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=True,
        already_complex=False, escalated=False) is True


def test_should_escalate_false_when_flag_off():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=False,
        already_complex=False, escalated=False) is False


def test_should_escalate_false_when_already_complex():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=True,
        already_complex=True, escalated=False) is False


def test_should_escalate_false_when_already_escalated():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=False, decompose_on_overflow=True,
        already_complex=False, escalated=True) is False


def test_should_escalate_false_when_doc_written():
    assert PydanticAIBackend._should_escalate(
        _overflow(), doc_exists=True, decompose_on_overflow=True,
        already_complex=False, escalated=False) is False


def test_should_escalate_false_on_other_exception():
    assert PydanticAIBackend._should_escalate(
        ValueError("nope"), doc_exists=False, decompose_on_overflow=True,
        already_complex=False, escalated=False) is False


# --- Task 4: run_module_agent retry loop ----------------------------------

class _FakeAgent:
    """Stand-in for pydantic-ai Agent: leaf run overflows; complex run writes the doc."""

    def __init__(self, model, name=None, deps_type=None, tools=None, system_prompt=None):
        self.tools = tools or []
        self.name = name

    async def run(self, prompt, deps=None, usage_limits=None):
        is_complex = generate_sub_module_documentation_tool in self.tools
        if not is_complex:
            raise IncompleteToolCall("output limit exceeded")
        with open(os.path.join(deps.absolute_docs_path,
                               f"{deps.current_module_name}.md"), "w", encoding="utf-8") as fh:
            fh.write("# decomposed doc\n")


def _backend(tmp_path, monkeypatch, *, decompose):
    monkeypatch.setattr(pab, "Agent", _FakeAgent)
    monkeypatch.setattr(pab, "create_fallback_models", lambda cfg: object())
    monkeypatch.setattr(pab, "build_usage_limits", lambda cfg: None)
    prof = resolve_profile("openai-compatible", "deepseek-chat",
                           {"decompose_on_overflow": decompose})
    cfg = Config(
        repo_path=str(tmp_path), output_dir=str(tmp_path), dependency_graph_dir=str(tmp_path),
        docs_dir=str(tmp_path), max_depth=3, llm_base_url="http://gw/v1", llm_api_key="k",
        main_model="deepseek-chat", cluster_model="deepseek-chat", fallback_model="fb",
        provider="openai-compatible", profile=prof,
    )
    with open(os.path.join(str(tmp_path), MODULE_TREE_FILENAME), "w", encoding="utf-8") as fh:
        json.dump({"Mod": {"components": [], "children": {}}}, fh)
    return pab.PydanticAIBackend(cfg)


@pytest.mark.asyncio
async def test_run_module_agent_escalates_on_overflow(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch, decompose=True)
    await backend.run_module_agent(
        module_name="Mod", components={}, core_component_ids=[],
        module_path=["Mod"], working_dir=str(tmp_path))
    assert os.path.exists(os.path.join(str(tmp_path), "Mod.md"))


@pytest.mark.asyncio
async def test_run_module_agent_reraises_when_flag_off(tmp_path, monkeypatch):
    backend = _backend(tmp_path, monkeypatch, decompose=False)
    with pytest.raises(IncompleteToolCall):
        await backend.run_module_agent(
            module_name="Mod", components={}, core_component_ids=[],
            module_path=["Mod"], working_dir=str(tmp_path))
    assert not os.path.exists(os.path.join(str(tmp_path), "Mod.md"))
