"""Tests for the Studio flow builder."""

from __future__ import annotations

import json
from typing import Any

from ivr_config import IVRConfig
from studio.flow_builder import build_flow_definition, dial_state_name, flow_friendly_name
from studio.widgets import (
    CONNECT_CALL_TYPE,
    CR_WIDGET_TYPE,
    HTTP_REQUEST_TYPE,
    SPLIT_TYPE,
    TWIML_REDIRECT_TYPE,
)

from tests.ivr.test_ivr_config import minimal_config_dict

LAMBDA_URL = "https://abc123.lambda-url.us-east-1.on.aws"
TOKEN = "test-session-token"


def two_intent_config() -> IVRConfig:
    raw = minimal_config_dict()
    raw["intents"].append(
        {
            "key": "sales",
            "name": "New business",
            "description": "Quotes and new policies.",
            "destination": {
                "type": "sip",
                "uri": "sip:sales@pbx.example.com",
                "headers": {"X-Dept": "sales"},
            },
        }
    )
    return IVRConfig.model_validate(raw)


def build(config: IVRConfig) -> dict[str, Any]:
    return build_flow_definition(config, LAMBDA_URL, TOKEN)


def states_by_name(definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {state["name"]: state for state in definition["states"]}


def test_definition_has_the_studio_envelope():
    definition = build(two_intent_config())
    assert definition["initial_state"] == "Trigger"
    assert definition["flags"] == {"allow_concurrent_calls": True}
    assert isinstance(definition["states"], list)


def test_every_transition_targets_a_state_that_exists():
    definition = build(two_intent_config())
    names = set(states_by_name(definition))
    for state in definition["states"]:
        for transition in state["transitions"]:
            target = transition.get("next")
            if target is not None:
                assert target in names, (
                    f"[phone/sip config] {state['name']} points at missing {target}"
                )


def test_every_transition_targets_a_state_that_exists_with_extensions():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"]["extension"] = "402"
    config = IVRConfig.model_validate(raw)
    definition = build(config)
    names = set(states_by_name(definition))
    for state in definition["states"]:
        for transition in state["transitions"]:
            target = transition.get("next")
            if target is not None:
                assert target in names, (
                    f"[extension config] {state['name']} points at missing {target}"
                )


def test_state_names_are_unique():
    definition = build(two_intent_config())
    names = [state["name"] for state in definition["states"]]
    assert len(names) == len(set(names))


def test_incoming_call_enters_the_session_fetch():
    states = states_by_name(build(two_intent_config()))
    transitions = {t["event"]: t.get("next") for t in states["Trigger"]["transitions"]}
    assert transitions["incomingCall"] == "get_session"


def test_incoming_message_is_not_handled_by_this_flow():
    states = states_by_name(build(two_intent_config()))
    transitions = {t["event"]: t.get("next") for t in states["Trigger"]["transitions"]}
    assert transitions["incomingMessage"] is None


def test_session_widget_posts_the_call_sid_and_token_to_lambda():
    states = states_by_name(build(two_intent_config()))
    session = states["get_session"]
    assert session["type"] == HTTP_REQUEST_TYPE
    assert session["properties"]["url"] == f"{LAMBDA_URL}/session"
    assert session["properties"]["method"] == "POST"
    body = json.loads(session["properties"]["body"])
    assert body == {"CallSid": "{{trigger.call.CallSid}}", "Token": TOKEN}


def test_session_widget_strips_a_trailing_slash_from_the_lambda_url():
    definition = build_flow_definition(two_intent_config(), LAMBDA_URL + "/", TOKEN)
    session = states_by_name(definition)["get_session"]
    assert session["properties"]["url"] == f"{LAMBDA_URL}/session"


def test_session_failure_reaches_a_human():
    states = states_by_name(build(two_intent_config()))
    transitions = {t["event"]: t.get("next") for t in states["get_session"]["transitions"]}
    assert transitions["success"] == "ai_agent"
    assert transitions["failed"] == dial_state_name("fallback")


def test_relay_widget_reads_the_url_from_the_session_widget():
    states = states_by_name(build(two_intent_config()))
    relay = states["ai_agent"]
    assert relay["type"] == CR_WIDGET_TYPE
    assert relay["properties"]["url"] == "{{widgets.get_session.parsed.websocket_url}}"


def test_relay_widget_omits_the_welcome_greeting_because_the_agent_sends_it():
    states = states_by_name(build(two_intent_config()))
    assert "welcome_greeting" not in states["ai_agent"]["properties"]


def test_relay_widget_omits_unset_voice_settings():
    states = states_by_name(build(two_intent_config()))
    properties = states["ai_agent"]["properties"]
    assert "language" not in properties
    assert "tts_provider" not in properties


def test_relay_widget_includes_configured_voice_settings():
    raw = minimal_config_dict()
    raw["voice"] = {"language": "en-GB", "ttsProvider": "ElevenLabs"}
    states = states_by_name(build(IVRConfig.model_validate(raw)))
    properties = states["ai_agent"]["properties"]
    assert properties["language"] == "en-GB"
    assert properties["tts_provider"] == "ElevenLabs"


def test_relay_failure_reaches_a_human():
    states = states_by_name(build(two_intent_config()))
    transitions = {t["event"]: t.get("next") for t in states["ai_agent"]["transitions"]}
    assert transitions["success"] == "route_intent"
    assert transitions["failed"] == dial_state_name("fallback")


def test_route_splits_on_the_handoff_data_slug():
    states = states_by_name(build(two_intent_config()))
    route = states["route_intent"]
    assert route["type"] == SPLIT_TYPE
    assert route["properties"]["input"] == "{{widgets.ai_agent.HandoffData}}"


def test_route_has_a_branch_per_intent_plus_explicit_fallback_and_no_match():
    states = states_by_name(build(two_intent_config()))
    transitions = states["route_intent"]["transitions"]

    matched = {t["conditions"][0]["value"]: t["next"] for t in transitions if t["event"] == "match"}
    assert matched == {
        "billing": dial_state_name("billing"),
        "sales": dial_state_name("sales"),
        "fallback": dial_state_name("fallback"),
    }

    no_match = [t for t in transitions if t["event"] == "noMatch"]
    assert len(no_match) == 1
    assert no_match[0]["next"] == dial_state_name("fallback")


def test_route_conditions_compare_for_equality():
    states = states_by_name(build(two_intent_config()))
    condition = next(
        t["conditions"][0]
        for t in states["route_intent"]["transitions"]
        if t["event"] == "match" and t["conditions"][0]["value"] == "billing"
    )
    assert condition["type"] == "equal_to"
    assert condition["arguments"] == ["{{widgets.ai_agent.HandoffData}}"]


def test_plain_phone_destination_becomes_a_connect_call_widget():
    states = states_by_name(build(two_intent_config()))
    dial = states[dial_state_name("billing")]
    assert dial["type"] == CONNECT_CALL_TYPE
    assert dial["properties"]["noun"] == "number"
    assert dial["properties"]["to"] == "+15551230001"
    assert dial["properties"]["caller_id"] == "{{contact.channel.address}}"


def test_sip_destination_carries_encoded_headers():
    states = states_by_name(build(two_intent_config()))
    dial = states[dial_state_name("sales")]
    assert dial["properties"]["noun"] == "sip"
    assert dial["properties"]["to"] == "sip:sales@pbx.example.com?X-Dept=sales"


def test_sip_destination_passes_through_digest_credentials():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"] = {
        "type": "sip",
        "uri": "sip:support@pbx.example.com",
        "username": "twilio",
        "password": "s3cret",
    }
    states = states_by_name(build(IVRConfig.model_validate(raw)))
    properties = states[dial_state_name("billing")]["properties"]
    assert properties["sip_username"] == "twilio"
    assert properties["sip_password"] == "s3cret"


def test_client_destination_uses_the_client_noun():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"] = {"type": "client", "identity": "alice"}
    states = states_by_name(build(IVRConfig.model_validate(raw)))
    properties = states[dial_state_name("billing")]["properties"]
    assert properties["noun"] == "client"
    assert properties["to"] == "alice"


def test_extension_destination_redirects_to_the_lambda_dial_route():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"]["extension"] = "402"
    states = states_by_name(build(IVRConfig.model_validate(raw)))
    dial = states[dial_state_name("billing")]
    assert dial["type"] == TWIML_REDIRECT_TYPE
    assert dial["properties"]["url"] == f"{LAMBDA_URL}/dial?intent=billing"
    assert dial["properties"]["method"] == "POST"


def test_extension_destination_does_not_wait_for_control_to_return():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"]["extension"] = "402"
    states = states_by_name(build(IVRConfig.model_validate(raw)))
    assert states[dial_state_name("billing")]["properties"]["timeout"] == 0


def test_extension_destination_has_no_dial_status_check():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"]["extension"] = "402"
    states = states_by_name(build(IVRConfig.model_validate(raw)))
    assert "check_billing" not in states


def test_connect_call_completion_is_checked_before_apologising():
    states = states_by_name(build(two_intent_config()))
    dial = states[dial_state_name("billing")]
    transitions = {t["event"]: t.get("next") for t in dial["transitions"]}
    assert transitions["callCompleted"] == "check_billing"
    assert transitions["hangup"] is None

    check = states["check_billing"]
    assert check["properties"]["input"] == "{{widgets.dial_billing.DialCallStatus}}"
    answered = next(t for t in check["transitions"] if t["event"] == "match")
    assert answered["conditions"][0]["value"] == "completed"
    assert answered.get("next") is None
    unanswered = next(t for t in check["transitions"] if t["event"] == "noMatch")
    assert unanswered["next"] == "say_no_answer"


def test_no_answer_message_is_shared_and_terminal():
    definition = build(two_intent_config())
    states = states_by_name(definition)
    say = states["say_no_answer"]
    assert say["properties"]["say"]
    assert all(t.get("next") is None for t in say["transitions"])
    assert len([s for s in definition["states"] if s["name"] == "say_no_answer"]) == 1


def test_every_state_has_a_canvas_offset():
    definition = build(two_intent_config())
    for state in definition["states"]:
        offset = state["properties"]["offset"]
        assert isinstance(offset["x"], int)
        assert isinstance(offset["y"], int)


def test_dial_widgets_do_not_overlap_on_the_canvas():
    definition = build(two_intent_config())
    dial_offsets = [
        (state["properties"]["offset"]["x"], state["properties"]["offset"]["y"])
        for state in definition["states"]
        if state["name"].startswith("dial_")
    ]
    assert len(dial_offsets) == len(set(dial_offsets))


def test_friendly_name_includes_the_business_name():
    assert "Owl Insurance" in flow_friendly_name(two_intent_config())


def test_definition_is_json_serializable():
    json.dumps(build(two_intent_config()))
