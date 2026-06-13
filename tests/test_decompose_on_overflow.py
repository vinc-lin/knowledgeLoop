"""Reactive decompose-on-overflow: profile flag, escalation decision, agent wiring."""

from codewiki.src.be.model_profiles import resolve_profile


# --- Task 1: ModelProfile.decompose_on_overflow ---------------------------

def test_decompose_on_overflow_default_true():
    p = resolve_profile("openai-compatible", "deepseek-chat")
    assert p.decompose_on_overflow is True


def test_decompose_on_overflow_user_override_false():
    p = resolve_profile("openai-compatible", "deepseek-chat",
                        {"decompose_on_overflow": False})
    assert p.decompose_on_overflow is False


from codewiki.src.be.pydantic_ai_backend import PydanticAIBackend
from codewiki.src.be.agent_tools.generate_sub_module_documentations import (
    generate_sub_module_documentation_tool,
)


def test_tools_for_leaf_excludes_submodule_tool():
    tools = PydanticAIBackend._tools_for(False)
    assert generate_sub_module_documentation_tool not in tools


def test_tools_for_complex_includes_submodule_tool():
    tools = PydanticAIBackend._tools_for(True)
    assert generate_sub_module_documentation_tool in tools


from pydantic_ai.exceptions import IncompleteToolCall


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
