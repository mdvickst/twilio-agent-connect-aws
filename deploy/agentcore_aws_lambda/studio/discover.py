"""Probe the Studio Flows API for the ConversationRelay widget's type string.

Uses POST /v2/Flows/Validate, which checks a definition against the real schema
without creating a flow, so this is free to run repeatedly.

Usage, from deploy/agentcore_aws_lambda with credentials in .env:

    python -m studio.discover
"""

from __future__ import annotations

import os
import sys
from typing import Any

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from .widgets import CR_WIDGET_TYPE_CANDIDATES


def candidate_definition(widget_type: str) -> dict[str, Any]:
    """A minimal two-state flow using ``widget_type`` for the relay widget."""
    return {
        "description": "ConversationRelay widget type probe",
        "initial_state": "Trigger",
        "flags": {"allow_concurrent_calls": True},
        "states": [
            {
                "name": "Trigger",
                "type": "trigger",
                "transitions": [{"event": "incomingCall", "next": "probe"}],
                "properties": {"offset": {"x": 0, "y": 0}},
            },
            {
                "name": "probe",
                "type": widget_type,
                "transitions": [{"event": "success"}, {"event": "failed"}],
                "properties": {
                    "url": "wss://example.com/relay",
                    "offset": {"x": 0, "y": 200},
                },
            },
        ],
    }


def probe_widget_type(client: Client, candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate type the Flows API accepts, or None."""
    for candidate in candidates:
        try:
            result = client.studio.v2.flow_validate.update(
                friendly_name="conversationrelay-type-probe",
                status="draft",
                definition=candidate_definition(candidate),
            )
        except TwilioRestException as error:
            print(f"  {candidate}: rejected ({error.status} {error.msg})")
            continue

        if result.valid:
            print(f"  {candidate}: ACCEPTED")
            return candidate
        print(f"  {candidate}: rejected (valid=false)")
    return None


def main() -> int:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    api_key = os.environ.get("TWILIO_API_KEY")
    api_secret = os.environ.get("TWILIO_API_SECRET")
    if not (account_sid and api_key and api_secret):
        print(
            "Set TWILIO_ACCOUNT_SID, TWILIO_API_KEY and TWILIO_API_SECRET "
            "(source your .env first).",
            file=sys.stderr,
        )
        return 2

    client = Client(api_key, api_secret, account_sid)

    print("Probing ConversationRelay widget type...")
    found = probe_widget_type(client, CR_WIDGET_TYPE_CANDIDATES)
    if not found:
        print(
            "\nNone of the candidates were accepted. Build a ConversationRelay "
            "widget in the Studio Console, then run:\n"
            "  twilio api:studio:v2:flows:fetch --sid FWxxxx -o json\n"
            "and read the widget's 'type' out of the definition.",
            file=sys.stderr,
        )
        return 1

    print(f"\nSet CR_WIDGET_TYPE = {found!r} in studio/widgets.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
