"""IVR-specific Lambda routes.

``/session`` mints the AgentCore presigned WebSocket URL for a call, because
Studio cannot sign an AWS request itself. ``/dial`` returns TwiML for
destinations that need DTMF, because Studio's Connect Call To widget has no
sendDigits.

Both are written as plain functions taking their dependencies as arguments so
they can be tested without AWS or Twilio.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Callable
from typing import Any, Protocol
from xml.sax.saxutils import quoteattr

from tac.core.logging import get_logger

logger = get_logger(__name__)

SESSION_PATH = "/session"
DIAL_PATH = "/dial"

UNAVAILABLE_MESSAGE = "Sorry, that option is not available right now. Please call again later."


class SignatureValidator(Protocol):
    """The slice of TwilioSignatureValidator these routes depend on."""

    def validate(self, event: dict[str, Any]) -> bool: ...


def json_response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Lambda Function URL JSON response."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def twiml_response(twiml: str) -> dict[str, Any]:
    """Build a Lambda Function URL TwiML response."""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/xml"},
        "body": twiml,
    }


def _request_method(event: dict[str, Any]) -> str:
    context = event.get("requestContext") or {}
    http = context.get("http") or {}
    return str(http.get("method", "")).upper()


def _decode_body(event: dict[str, Any]) -> str | None:
    """Return the request body as text, or None if it cannot be decoded."""
    body: str = event.get("body") or ""
    if not body:
        return ""
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body).decode("utf-8")
        except (TypeError, binascii.Error, UnicodeDecodeError) as error:
            logger.warning(f"Failed to decode request body: {error}")
            return None
    return body


def extract_call_sid(event: dict[str, Any]) -> str | None:
    """Pull ``CallSid`` out of a JSON request body."""
    body = _decode_body(event)
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    call_sid = parsed.get("CallSid")
    return call_sid if isinstance(call_sid, str) and call_sid else None


def _parse_json_body(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return the parsed JSON body dict, or None if body is missing/invalid."""
    body = _decode_body(event)
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def handle_session(
    event: dict[str, Any],
    *,
    expected_token: str,
    presign: Callable[[str], str],
) -> dict[str, Any]:
    """Mint a presigned AgentCore WebSocket URL for the call in this request.

    Args:
        event: Lambda Function URL event.
        expected_token: The shared token embedded in the Studio flow.
        presign: Callable taking a CallSid and returning a ``wss://`` URL.

    Returns:
        A Lambda response. 200 with ``{"websocket_url": ...}`` on success; 403 on
        a bad or missing token (including an unparseable body), 405 on a non-POST,
        400 on a missing or invalid ``CallSid`` in an authenticated request, 500 if
        the deployment has no token configured or presigning fails.
    """
    if _request_method(event) != "POST":
        return json_response(405, {"error": "Method not allowed"})

    if not expected_token:
        logger.error("IVR_SESSION_TOKEN is not configured; refusing to mint session URLs")
        return json_response(500, {"error": "Server misconfigured"})

    # Authenticate before doing any work on untrusted input — this route is publicly
    # reachable. The token lives inside the JSON body, so a body that does not parse
    # simply cannot carry a valid token and fails authentication (returns 403, not 400).
    parsed = _parse_json_body(event)
    submitted_token = parsed.get("Token") if parsed is not None else ""
    if not isinstance(submitted_token, str):
        submitted_token = ""

    if not hmac.compare_digest(submitted_token, expected_token):
        logger.warning("Rejected /session request with an invalid token")
        return json_response(403, {"error": "Forbidden"})

    # parsed is guaranteed non-None here: compare_digest would have failed otherwise.
    call_sid = parsed.get("CallSid")  # type: ignore[union-attr]
    if not isinstance(call_sid, str) or not call_sid:
        return json_response(400, {"error": "Missing CallSid"})

    try:
        websocket_url = presign(call_sid)
    except Exception as error:
        logger.error(f"Failed to presign AgentCore URL: {error}", exc_info=True)
        return json_response(500, {"error": "Internal server error"})

    return json_response(200, {"websocket_url": websocket_url})


def _hangup_twiml(message: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Response><Say>{message}</Say><Hangup/></Response>'
    )


def _dial_twiml(number: str, send_digits: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Dial>"
        f"<Number sendDigits={quoteattr(send_digits)}>{_escape_text(number)}</Number>"
        "</Dial></Response>"
    )


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def handle_dial(
    event: dict[str, Any],
    *,
    destinations: dict[str, dict[str, str]],
    validator: SignatureValidator,
) -> dict[str, Any]:
    """Return TwiML dialing a destination that needs DTMF digits.

    Args:
        event: Lambda Function URL event, fetched by Twilio Voice and therefore
            carrying ``X-Twilio-Signature``.
        destinations: Map of intent key to ``{"number": ..., "sendDigits": ...}``.
        validator: Twilio signature validator.

    Returns:
        A Lambda response. 200 with ``<Dial>`` TwiML on success, 200 with a spoken
        apology and ``<Hangup/>`` for an unknown intent, 403 on a bad signature.
        Never 500 into a live call.
    """
    if not validator.validate(event):
        return json_response(403, {"error": "Invalid webhook signature"})

    parameters = event.get("queryStringParameters") or {}
    intent = parameters.get("intent")

    destination = destinations.get(intent) if intent else None
    if destination is None:
        logger.warning(f"No extension destination configured for intent {intent!r}")
        return twiml_response(_hangup_twiml(UNAVAILABLE_MESSAGE))

    return twiml_response(_dial_twiml(destination["number"], destination["sendDigits"]))
