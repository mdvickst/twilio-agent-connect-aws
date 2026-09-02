"""Remove the IVR's Studio flow and clear the phone number's voice webhook.

Best-effort: individual Twilio operations are each attempted and any failures
are reported, but a single failure does not prevent the remaining cleanup from
running.  Exits non-zero if any step could not be completed so that
``make destroy`` surfaces the problem without pretending success.

Usage, from the repository root with credentials exported:

    PYTHONPATH=deploy/agentcore_aws_lambda uv run python -m studio.teardown
"""

from __future__ import annotations

import os
import sys

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from .flow_builder import flow_friendly_name
from .provision import find_flow_by_name


def main() -> int:
    """Clear the number's voice webhook then delete the Studio flow.

    Returns:
        0 on full success, non-zero if any cleanup step failed.
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    api_key = os.environ.get("TWILIO_API_KEY")
    api_secret = os.environ.get("TWILIO_API_SECRET")

    if not (account_sid and api_key and api_secret):
        print(
            "Set TWILIO_ACCOUNT_SID, TWILIO_API_KEY and TWILIO_API_SECRET. "
            "Run 'make configure' first.",
            file=sys.stderr,
        )
        return 2

    try:
        from ivr_config import load_config

        config = load_config()
    except FileNotFoundError as exc:
        print(f"Could not load ivr-config.json: {exc}", file=sys.stderr)
        print("Cannot determine which flow to delete. Teardown incomplete.", file=sys.stderr)
        return 1

    client = Client(api_key, api_secret, account_sid)
    failed = False

    # Step 1: clear the phone number's voice webhook before deleting the flow,
    # so no call can arrive at a number pointing to a flow being deleted.
    print(f"Clearing voice webhook for {config.twilio.phone_number}...")
    try:
        client.incoming_phone_numbers(config.twilio.phone_number_sid).update(
            voice_url="", voice_method="POST"
        )
        print("  Cleared.")
    except TwilioRestException as exc:
        print(f"  Could not clear webhook: {exc.status} {exc.msg}", file=sys.stderr)
        failed = True

    # Step 2: delete the flow.
    friendly_name = flow_friendly_name(config)
    print(f"Deleting Studio flow {friendly_name!r}...")
    try:
        flow = find_flow_by_name(client, friendly_name)
        if flow is None:
            print(f"  Flow {friendly_name!r} not found — already deleted or never deployed.")
        else:
            client.studio.v2.flows(flow.sid).delete()
            print(f"  Deleted (SID {flow.sid}).")
    except TwilioRestException as exc:
        print(f"  Could not delete flow: {exc.status} {exc.msg}", file=sys.stderr)
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
