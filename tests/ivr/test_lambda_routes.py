"""Tests for the IVR-specific Lambda routes."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from routes import handle_dial, handle_session

PRESIGNED = "wss://runtime.bedrock-agentcore.us-east-1.amazonaws.com/x?X-Amz-Signature=abc"
TOKEN = "correct-horse-battery-staple"


def presign(call_sid: str) -> str:
    return f"{PRESIGNED}&session={call_sid}"


def session_event(body: dict[str, Any] | str, *, base64_encoded: bool = False) -> dict[str, Any]:
    raw = body if isinstance(body, str) else json.dumps(body)
    if base64_encoded:
        raw = base64.b64encode(raw.encode()).decode()
    return {
        "rawPath": "/session",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"content-type": "application/json"},
        "body": raw,
        "isBase64Encoded": base64_encoded,
    }


class AcceptingValidator:
    def validate(self, event: dict[str, Any]) -> bool:
        return True


class RejectingValidator:
    def validate(self, event: dict[str, Any]) -> bool:
        return False


def dial_event(intent: str) -> dict[str, Any]:
    return {
        "rawPath": "/dial",
        "rawQueryString": f"intent={intent}",
        "queryStringParameters": {"intent": intent},
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "body": "CallSid=CA1",
        "isBase64Encoded": False,
    }


DESTINATIONS = {
    "billing": {"number": "+15551230001", "sendDigits": "wwww402"},
    "fallback": {"number": "+15551230000", "sendDigits": "wwww0"},
}


# --- /session -------------------------------------------------------------


def test_session_returns_the_presigned_websocket_url():
    event = session_event({"CallSid": "CA123", "Token": TOKEN})
    response = handle_session(event, expected_token=TOKEN, presign=presign)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["websocket_url"] == presign("CA123")


def test_session_reads_a_base64_encoded_body():
    event = session_event({"CallSid": "CA123", "Token": TOKEN}, base64_encoded=True)
    response = handle_session(event, expected_token=TOKEN, presign=presign)
    assert response["statusCode"] == 200


def test_session_rejects_a_wrong_token():
    event = session_event({"CallSid": "CA123", "Token": "guess"})
    response = handle_session(event, expected_token=TOKEN, presign=presign)
    assert response["statusCode"] == 403


def test_session_rejects_a_missing_token():
    event = session_event({"CallSid": "CA123"})
    response = handle_session(event, expected_token=TOKEN, presign=presign)
    assert response["statusCode"] == 403


def test_session_rejects_a_non_post_request():
    event = session_event({"CallSid": "CA123", "Token": TOKEN})
    event["requestContext"]["http"]["method"] = "GET"
    response = handle_session(event, expected_token=TOKEN, presign=presign)
    assert response["statusCode"] == 405


def test_session_rejects_a_missing_call_sid():
    event = session_event({"Token": TOKEN})
    response = handle_session(event, expected_token=TOKEN, presign=presign)
    assert response["statusCode"] == 400


def test_session_rejects_invalid_json():
    event = session_event("not json at all")
    response = handle_session(event, expected_token=TOKEN, presign=presign)
    assert response["statusCode"] == 400


def test_session_refuses_to_run_without_a_configured_token():
    event = session_event({"CallSid": "CA123", "Token": ""})
    response = handle_session(event, expected_token="", presign=presign)
    assert response["statusCode"] == 500


def test_session_never_leaks_the_token_in_an_error_body():
    event = session_event({"CallSid": "CA123", "Token": "guess"})
    response = handle_session(event, expected_token=TOKEN, presign=presign)
    assert TOKEN not in response["body"]


def test_session_reports_a_presigning_failure_as_a_server_error():
    def broken_presign(call_sid: str) -> str:
        raise RuntimeError("no credentials")

    event = session_event({"CallSid": "CA123", "Token": TOKEN})
    response = handle_session(event, expected_token=TOKEN, presign=broken_presign)
    assert response["statusCode"] == 500


# --- /dial ----------------------------------------------------------------


def test_dial_returns_twiml_with_send_digits():
    response = handle_dial(
        dial_event("billing"), destinations=DESTINATIONS, validator=AcceptingValidator()
    )

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/xml"
    assert 'sendDigits="wwww402"' in response["body"]
    assert "+15551230001" in response["body"]
    assert "<Dial" in response["body"]


def test_dial_rejects_an_invalid_signature():
    response = handle_dial(
        dial_event("billing"), destinations=DESTINATIONS, validator=RejectingValidator()
    )
    assert response["statusCode"] == 403


def test_dial_speaks_and_hangs_up_on_an_unknown_intent():
    response = handle_dial(
        dial_event("mortgages"), destinations=DESTINATIONS, validator=AcceptingValidator()
    )

    assert response["statusCode"] == 200
    assert "<Say" in response["body"]
    assert "<Hangup" in response["body"]
    assert "<Dial" not in response["body"]


def test_dial_speaks_and_hangs_up_when_the_intent_is_missing():
    event = dial_event("billing")
    event["queryStringParameters"] = {}
    event["rawQueryString"] = ""
    response = handle_dial(event, destinations=DESTINATIONS, validator=AcceptingValidator())

    assert response["statusCode"] == 200
    assert "<Hangup" in response["body"]


def test_dial_escapes_xml_special_characters_in_the_number():
    destinations = {"weird": {"number": "+1555&0001", "sendDigits": "ww1"}}
    response = handle_dial(
        dial_event("weird"), destinations=destinations, validator=AcceptingValidator()
    )
    assert "&amp;" in response["body"]
    assert "+1555&0001" not in response["body"]


@pytest.mark.parametrize("intent", ["billing", "fallback"])
def test_dial_serves_every_configured_extension_destination(intent: str):
    response = handle_dial(
        dial_event(intent), destinations=DESTINATIONS, validator=AcceptingValidator()
    )
    assert DESTINATIONS[intent]["number"] in response["body"]
