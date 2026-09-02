"""Tests for IVR system prompt assembly."""

from __future__ import annotations

from ivr_config import IVRConfig
from prompt import build_sms_system_prompt, build_voice_system_prompt, render_intent_catalog

from tests.ivr.test_ivr_config import minimal_config_dict


def config_with_two_intents() -> IVRConfig:
    raw = minimal_config_dict()
    raw["intents"].append(
        {
            "key": "sales",
            "name": "New business",
            "description": "Caller wants a quote or a new policy.",
            "destination": {"type": "sip", "uri": "sip:sales@pbx.example.com"},
        }
    )
    return IVRConfig.model_validate(raw)


def test_intent_catalog_lists_every_key_and_the_fallback():
    catalog = render_intent_catalog(config_with_two_intents())
    assert "billing" in catalog
    assert "sales" in catalog
    assert "fallback" in catalog


def test_intent_catalog_includes_names_and_descriptions():
    catalog = render_intent_catalog(config_with_two_intents())
    assert "New business" in catalog
    assert "Caller wants a quote or a new policy." in catalog


def test_voice_prompt_includes_business_context_and_catalog():
    prompt = build_voice_system_prompt(config_with_two_intents())
    assert "Owl Insurance" in prompt
    assert "Owl Insurance sells home and auto policies." in prompt
    assert "billing" in prompt


def test_voice_prompt_names_the_transfer_tool_and_the_fallback():
    prompt = build_voice_system_prompt(config_with_two_intents())
    assert "transfer_call" in prompt
    assert "Operator" in prompt


def test_voice_prompt_forbids_markdown_because_it_is_read_aloud():
    prompt = build_voice_system_prompt(config_with_two_intents())
    assert "markdown" in prompt.lower()


def test_sms_prompt_has_no_transfer_tool_instructions():
    prompt = build_sms_system_prompt(config_with_two_intents())
    assert "transfer_call" not in prompt


def test_sms_prompt_gives_callers_the_phone_number_to_reach_a_department():
    prompt = build_sms_system_prompt(config_with_two_intents())
    assert "+15550000000" in prompt


# --- Additional rule assertions (Finding 4) --------------------------------


def test_sms_prompt_does_not_contain_transfer_wording():
    """SMS prompt must not suggest the agent can transfer — it has no transfer tool."""
    prompt = build_sms_system_prompt(config_with_two_intents())
    assert "transfer" not in prompt.lower()
    assert "Options you can transfer to:" not in prompt


def test_sms_prompt_forbids_markdown():
    prompt = build_sms_system_prompt(config_with_two_intents())
    assert "markdown" in prompt.lower()


def test_voice_prompt_pins_two_attempts_rule():
    prompt = build_voice_system_prompt(config_with_two_intents())
    assert "two" in prompt.lower() and "attempt" in prompt.lower()


def test_voice_prompt_pins_at_most_one_question_per_turn():
    prompt = build_voice_system_prompt(config_with_two_intents())
    assert "one question" in prompt.lower() or "at most one" in prompt.lower()
