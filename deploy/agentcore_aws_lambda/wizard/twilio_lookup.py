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


#: Matches ``GET /2010-04-01/Accounts.json?PageSize=20``.
ACCOUNT_LIST_LIMIT = 20


class AccountMismatchError(Exception):
    """The API key authenticates, but not for the Account SID that was entered.

    Worth its own type: everything downstream — the Studio flow, the Lambda, the
    Orchestrator configuration — is keyed on the Account SID the user typed, so
    proceeding with a key for a different account would silently misconfigure the
    whole deployment rather than fail here.
    """


def _client(credentials: TwilioCredentials) -> Client:
    return Client(credentials.api_key, credentials.api_secret, credentials.account_sid)


def verify(credentials: TwilioCredentials) -> str:
    """Confirm the credentials work and return the account's friendly name.

    Lists accounts (``GET /2010-04-01/Accounts.json``) rather than fetching
    ``/Accounts/{sid}``. The fetch requires a **Main** API key — a Standard key
    gets 20003 on it — and requiring a Main key just to populate two dropdowns
    would be a poor trade for the customer. The list works with a Standard key.

    Raises:
        AccountMismatchError: If the key works but cannot see the Account SID
            entered, or sees no accounts at all.
    """
    accounts = _client(credentials).api.v2010.accounts.list(limit=ACCOUNT_LIST_LIMIT)

    for account in accounts:
        if account.sid == credentials.account_sid:
            return str(account.friendly_name or account.sid)

    visible = ", ".join(a.sid for a in accounts if a.sid) or "none"
    raise AccountMismatchError(
        f"The API key authenticated, but it cannot see account "
        f"{credentials.account_sid}. Accounts this key can see: {visible}."
    )


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
    """Voice-capable numbers on the account."""
    numbers = _client(credentials).incoming_phone_numbers.list(limit=200)
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
