"""Best-effort helper that adds the Orchestrator capture rules the IVR needs.

TAC's Orchestrator client is read-only for configurations, so this writes through
the Control Plane API directly. The exact write contract is not documented in this
repo, so every failure path falls back to printing the Console steps rather than
pretending the rules were added. The Task 8 preflight is the real enforcement.

Usage, from the repository root with the example's .env exported:

    PYTHONPATH=deploy/agentcore_aws_lambda uv run python -m studio.capture_rules
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx
from ivr_config import load_config

from .preflight import REQUIRED_CHANNELS, format_problems

CONTROL_PLANE_BASE = "https://conversations.twilio.com/v2/ControlPlane/Configurations"


def add_capture_rules(
    configuration: dict[str, Any], number: str, channels: tuple[str, ...] = REQUIRED_CHANNELS
) -> dict[str, Any]:
    """Return a copy of the raw configuration with a capture rule per channel.

    Existing rules are preserved; a rule for ``number`` is appended only where one
    is not already present.
    """
    updated = dict(configuration)
    channel_settings = dict(updated.get("channelSettings") or {})

    for channel in channels:
        existing_key = next(
            (key for key in channel_settings if key.upper() == channel.upper()), channel
        )
        settings = dict(channel_settings.get(existing_key) or {})
        rules = list(settings.get("captureRules") or [])
        if not any(rule.get("to") in (number, "*") for rule in rules):
            rules.append({"from": "*", "to": number})
        settings["captureRules"] = rules
        channel_settings[existing_key] = settings

    updated["channelSettings"] = channel_settings
    return updated


def main() -> int:
    api_key = os.environ.get("TWILIO_API_KEY")
    api_secret = os.environ.get("TWILIO_API_SECRET")
    if not (api_key and api_secret):
        print("Set TWILIO_API_KEY and TWILIO_API_SECRET.", file=sys.stderr)
        return 2

    config = load_config()
    configuration_id = config.twilio.conversation_configuration_id
    url = f"{CONTROL_PLANE_BASE}/{configuration_id}"
    auth = (api_key, api_secret)

    with httpx.Client(auth=auth, timeout=30.0, follow_redirects=True) as client:
        fetched = client.get(url)
        if fetched.status_code != 200:
            print(f"Could not read {configuration_id}: {fetched.status_code}", file=sys.stderr)
            print(format_problems(["Unable to read the configuration"], config), file=sys.stderr)
            return 1

        try:
            body = fetched.json()
        except Exception:
            print(f"Could not parse response from {configuration_id} as JSON", file=sys.stderr)
            print(format_problems(["Unable to read the configuration"], config), file=sys.stderr)
            return 1
        payload = add_capture_rules(body, config.twilio.phone_number)
        written = client.put(url, json=payload)

    if written.status_code not in (200, 201, 204):
        print(
            f"Could not update {configuration_id}: {written.status_code} {written.text}",
            file=sys.stderr,
        )
        print(
            format_problems(["Automatic capture-rule setup failed; add them by hand"], config),
            file=sys.stderr,
        )
        return 1

    print(f"Capture rules added for {config.twilio.phone_number}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
