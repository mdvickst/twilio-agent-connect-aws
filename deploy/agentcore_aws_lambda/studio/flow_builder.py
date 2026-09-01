"""Compile an IVR config into a Twilio Studio flow definition.

Pure: no network, no credentials, no clock. Everything here is a function of the
config plus the deployed Lambda URL and session token, which is what makes the
generated flow snapshot-testable.

Flow shape:

    Trigger (incomingCall)
      -> get_session      fetch the AgentCore presigned wss URL from Lambda
      -> ai_agent         ConversationRelay against that URL
      -> route_intent     split on the HandoffData slug
      -> dial_<key>       connect-call-to, or add-twiml-redirect for extensions
      -> check_<key>      only for connect-call-to: was it actually answered?
      -> say_no_answer    shared apology for unanswered destinations
"""

from __future__ import annotations

import json
from typing import Any

from ivr_config import (
    FALLBACK_KEY,
    ClientDestination,
    Destination,
    IVRConfig,
    PhoneDestination,
    SipDestination,
)

from .widgets import (
    CONNECT_CALL_TYPE,
    CR_URL_PROPERTY,
    CR_VOICE_PROPERTY_MAP,
    CR_WIDGET_TYPE,
    HTTP_REQUEST_TYPE,
    SAY_PLAY_TYPE,
    SPLIT_TYPE,
    TRIGGER_TYPE,
    TWIML_REDIRECT_TYPE,
)

TRIGGER_STATE = "Trigger"
SESSION_STATE = "get_session"
RELAY_STATE = "ai_agent"
ROUTE_STATE = "route_intent"
NO_ANSWER_STATE = "say_no_answer"

#: Liquid expression exposing the slug the agent sent in its end message.
HANDOFF_DATA = f"{{{{widgets.{RELAY_STATE}.HandoffData}}}}"

#: Caller ID for outbound legs: the number the caller originally dialed.
CALLER_ID = "{{contact.channel.address}}"

DIAL_TIMEOUT_SECONDS = 30

NO_ANSWER_MESSAGE = (
    "Sorry, no one is available to take your call right now. Please try again later."
)

# Canvas layout. Studio does not care, but a customer opening the flow does.
_COLUMN_WIDTH = 260
_FIRST_COLUMN_X = -260
_DIAL_ROW_Y = 850
_CHECK_ROW_Y = 1050


def dial_state_name(key: str) -> str:
    """Widget name for the destination belonging to ``key``."""
    return f"dial_{key}"


def check_state_name(key: str) -> str:
    """Widget name for the dial-status check belonging to ``key``."""
    return f"check_{key}"


def flow_friendly_name(config: IVRConfig) -> str:
    """Friendly name used to find and update this flow idempotently."""
    return f"TAC AI IVR — {config.business.name}"


def _equal_to(value: str, argument: str, label: str) -> dict[str, Any]:
    return {
        "friendly_name": label,
        "arguments": [argument],
        "type": "equal_to",
        "value": value,
    }


def _trigger_state() -> dict[str, Any]:
    """Entry point.

    Only ``incomingCall`` is wired. SMS reaches the agent through Conversation
    Orchestrator and the Lambda ``/webhook`` route, not through this flow.
    """
    return {
        "name": TRIGGER_STATE,
        "type": TRIGGER_TYPE,
        "transitions": [
            {"event": "incomingCall", "next": SESSION_STATE},
            {"event": "incomingMessage"},
            {"event": "incomingConversationMessage"},
            {"event": "incomingRequest"},
            {"event": "incomingParent"},
        ],
        "properties": {"offset": {"x": 0, "y": 0}},
    }


def _session_state(lambda_url: str, session_token: str) -> dict[str, Any]:
    """Fetch the AgentCore presigned WebSocket URL for this call.

    Studio's HTTP Request widget cannot send custom headers, so the shared token
    travels in the JSON body and the Lambda compares it in constant time.
    """
    body = json.dumps({"CallSid": "{{trigger.call.CallSid}}", "Token": session_token})
    return {
        "name": SESSION_STATE,
        "type": HTTP_REQUEST_TYPE,
        "transitions": [
            {"event": "success", "next": RELAY_STATE},
            {"event": "failed", "next": dial_state_name(FALLBACK_KEY)},
        ],
        "properties": {
            "method": "POST",
            "content_type": "application/json;charset=utf-8",
            "url": f"{lambda_url.rstrip('/')}/session",
            "body": body,
            "offset": {"x": 150, "y": 220},
        },
    }


def _relay_state(config: IVRConfig) -> dict[str, Any]:
    """Run ConversationRelay against the URL the session widget returned.

    ``welcome_greeting`` is deliberately absent: TACAgentCoreWebSocketAdapter
    sends the greeting on the setup message, and setting both would greet twice.
    """
    properties: dict[str, Any] = {
        CR_URL_PROPERTY: f"{{{{widgets.{SESSION_STATE}.parsed.websocket_url}}}}",
        "offset": {"x": 150, "y": 440},
    }
    for field_name, property_name in CR_VOICE_PROPERTY_MAP.items():
        value = getattr(config.voice, field_name, None)
        if value:
            properties[property_name] = value

    return {
        "name": RELAY_STATE,
        "type": CR_WIDGET_TYPE,
        "transitions": [
            {"event": "success", "next": ROUTE_STATE},
            {"event": "failed", "next": dial_state_name(FALLBACK_KEY)},
        ],
        "properties": properties,
    }


def _route_state(config: IVRConfig) -> dict[str, Any]:
    """Split on the handoff slug.

    Emits an explicit ``fallback`` branch as well as ``noMatch``: the agent can
    name the fallback deliberately when a caller asks for a person, and an empty
    or unrecognized slug lands in the same place.
    """
    transitions: list[dict[str, Any]] = [
        {"event": "noMatch", "next": dial_state_name(FALLBACK_KEY)}
    ]
    for key in [*config.intent_keys, FALLBACK_KEY]:
        transitions.append(
            {
                "event": "match",
                "next": dial_state_name(key),
                "conditions": [_equal_to(key, HANDOFF_DATA, f"HandoffData is {key}")],
            }
        )

    return {
        "name": ROUTE_STATE,
        "type": SPLIT_TYPE,
        "transitions": transitions,
        "properties": {"input": HANDOFF_DATA, "offset": {"x": 150, "y": 660}},
    }


def _connect_call_state(
    key: str, destination: Destination, offset: dict[str, int]
) -> dict[str, Any]:
    """Bridge the caller to a destination using Studio's native dial widget."""
    properties: dict[str, Any] = {
        "caller_id": CALLER_ID,
        "timeout": DIAL_TIMEOUT_SECONDS,
        "offset": offset,
    }

    if isinstance(destination, PhoneDestination):
        properties["noun"] = "number"
        properties["to"] = destination.number
    elif isinstance(destination, SipDestination):
        properties["noun"] = "sip"
        properties["to"] = destination.dial_target
        if destination.username:
            properties["sip_username"] = destination.username
        if destination.password:
            properties["sip_password"] = destination.password
    elif isinstance(destination, ClientDestination):
        properties["noun"] = "client"
        properties["to"] = destination.identity
    else:  # pragma: no cover - the discriminated union makes this unreachable
        raise TypeError(f"Unsupported destination type: {type(destination).__name__}")

    return {
        "name": dial_state_name(key),
        "type": CONNECT_CALL_TYPE,
        "transitions": [
            {"event": "callCompleted", "next": check_state_name(key)},
            {"event": "hangup"},
        ],
        "properties": properties,
    }


def _dial_check_state(key: str, offset: dict[str, int]) -> dict[str, Any]:
    """Distinguish "answered then ended" from "busy, rejected, or never answered".

    Connect Call To fires ``callCompleted`` for both, so without this the apology
    would play after successful calls too.
    """
    status = f"{{{{widgets.{dial_state_name(key)}.DialCallStatus}}}}"
    return {
        "name": check_state_name(key),
        "type": SPLIT_TYPE,
        "transitions": [
            {"event": "noMatch", "next": NO_ANSWER_STATE},
            {
                "event": "match",
                "conditions": [_equal_to("completed", status, "Answered and completed")],
            },
        ],
        "properties": {"input": status, "offset": offset},
    }


def _twiml_redirect_state(key: str, lambda_url: str, offset: dict[str, int]) -> dict[str, Any]:
    """Hand the call to Lambda-generated TwiML so an extension can be dialed.

    Studio's dial widget has no sendDigits. ``timeout: 0`` declares that control
    will not return to the flow — the Lambda returns a bare ``<Dial>``, and per
    Twilio's docs a flow can only regain a voice call if the TwiML redirects back
    with ``FlowEvent=return``.
    """
    return {
        "name": dial_state_name(key),
        "type": TWIML_REDIRECT_TYPE,
        "transitions": [
            {"event": "return"},
            {"event": "timeout"},
            {"event": "failed"},
        ],
        "properties": {
            "url": f"{lambda_url.rstrip('/')}/dial?intent={key}",
            "method": "POST",
            "timeout": 0,
            "offset": offset,
        },
    }


def _no_answer_state(offset: dict[str, int]) -> dict[str, Any]:
    """Shared apology for destinations that did not pick up."""
    return {
        "name": NO_ANSWER_STATE,
        "type": SAY_PLAY_TYPE,
        "transitions": [{"event": "audioComplete"}],
        "properties": {"say": NO_ANSWER_MESSAGE, "loop": 1, "offset": offset},
    }


def _destination_states(config: IVRConfig, lambda_url: str) -> list[dict[str, Any]]:
    """One dial widget per intent plus the fallback, with status checks where possible."""
    targets: list[tuple[str, Destination]] = [
        (intent.key, intent.destination) for intent in config.intents
    ]
    targets.append((FALLBACK_KEY, config.fallback.destination))

    states: list[dict[str, Any]] = []
    for index, (key, destination) in enumerate(targets):
        column_x = _FIRST_COLUMN_X + _COLUMN_WIDTH * index
        needs_dtmf = (
            isinstance(destination, PhoneDestination) and destination.send_digits is not None
        )
        if needs_dtmf:
            states.append(_twiml_redirect_state(key, lambda_url, {"x": column_x, "y": _DIAL_ROW_Y}))
        else:
            states.append(_connect_call_state(key, destination, {"x": column_x, "y": _DIAL_ROW_Y}))
            states.append(_dial_check_state(key, {"x": column_x, "y": _CHECK_ROW_Y}))
    return states


def build_flow_definition(config: IVRConfig, lambda_url: str, session_token: str) -> dict[str, Any]:
    """Build the Studio flow definition for this IVR.

    Args:
        config: Validated IVR configuration.
        lambda_url: Base URL of the deployed Lambda function URL, with or without
            a trailing slash.
        session_token: Shared secret the ``/session`` route checks.

    Returns:
        A flow definition ready to pass as the ``Definition`` parameter of the
        Studio Flows API.
    """
    states: list[dict[str, Any]] = [
        _trigger_state(),
        _session_state(lambda_url, session_token),
        _relay_state(config),
        _route_state(config),
    ]
    states.extend(_destination_states(config, lambda_url))
    states.append(_no_answer_state({"x": 150, "y": 1250}))

    return {
        "description": f"AI IVR for {config.business.name}",
        "initial_state": TRIGGER_STATE,
        "flags": {"allow_concurrent_calls": True},
        "states": states,
    }
