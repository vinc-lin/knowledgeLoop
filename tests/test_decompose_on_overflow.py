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
