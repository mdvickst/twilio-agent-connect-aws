"""Read the customer's Twilio account to populate the wizard's dropdowns.

Nothing here creates or modifies Twilio resources.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field
from twilio.rest import Client

CONTROL_PLANE_CONFIGURATIONS = "https://conversations.twilio.com/v2/ControlPlane/Configurations"

REQUEST_TIMEOUT_SECONDS = 30.0


class TwilioCredentials(BaseModel):
    """Credentials submitted by the wizard form."""

    account_sid: str = Field(..., alias="accountSid", min_length=34, max_length=34)
    auth_token: str = Field(..., alias="authToken", min_length=1)
    api_key: str = Field(..., alias="apiKey", min_length=34, max_length=34)
    api_secret: str = Field(..., alias="apiSecret", min_length=1)

    model_config = {"populate_by_name": True}


MAX_PHONE_NUMBERS = 200


def _client(credentials: TwilioCredentials) -> Client:
    return Client(credentials.api_key, credentials.api_secret, credentials.account_sid)


def _supports_voice(number: Any) -> bool:
    """True unless the number explicitly lacks voice capability.

    The SDK annotates ``capabilities`` as ``Optional[str]`` but populates it
    straight from the JSON payload, where it is an object such as
    ``{"voice": true, "sms": true}``. Anything unexpected is treated as capable,
    so a usable number is never hidden from the wizard.
    """
    capabilities = getattr(number, "capabilities", None)
    if isinstance(capabilities, dict):
        return bool(capabilities.get("voice", True))
    return True


def list_phone_numbers(credentials: TwilioCredentials) -> list[dict[str, str]]:
    """Voice-capable numbers on the account.

    This doubles as the credential check. It reads
    ``/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json``, which is a
    normal resource a **Standard** API key can read, and which is scoped to the
    Account SID the user entered — so a 401 here means either the key/secret is
    wrong or the key has no access to that account. Both are what the user needs
    to know, and no extra request is needed to find it out.

    Deliberately does NOT touch ``/Accounts`` or ``/Accounts/{sid}``: those are
    account-management endpoints and require a **Main** key, which this wizard has
    no reason to ask for. See
    https://www.twilio.com/docs/iam/api-keys#types-of-api-keys
    """
    numbers = _client(credentials).incoming_phone_numbers.list(limit=MAX_PHONE_NUMBERS)
    return [
        {
            "sid": number.sid,
            "phoneNumber": number.phone_number,
            "friendlyName": number.friendly_name or number.phone_number,
        }
        for number in numbers
        if _supports_voice(number)
    ]


def list_conversation_configurations(
    credentials: TwilioCredentials,
) -> list[dict[str, str]]:
    """Conversation Orchestrator configurations on the account.

    TAC's client can fetch one configuration but cannot list them, so this calls
    the Control Plane API directly with API key basic auth.
    """
    auth = (credentials.api_key, credentials.api_secret)
    with httpx.Client(auth=auth, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = client.get(CONTROL_PLANE_CONFIGURATIONS)
        response.raise_for_status()
        payload = response.json()

    items = payload.get("configurations") or payload.get("items") or []
    return [
        {
            "id": item.get("id", ""),
            "displayName": item.get("displayName") or item.get("description") or item.get("id", ""),
        }
        for item in items
        if item.get("id")
    ]
