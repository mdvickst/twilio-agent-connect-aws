"""Tests for the wizard HTTP API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from wizard.server import create_app

from tests.ivr.test_ivr_config import minimal_config_dict

CREDENTIALS = {
    "accountSid": "AC" + "1" * 32,
    "authToken": "auth-token",
    "apiKey": "SK" + "2" * 32,
    "apiSecret": "api-secret",
}


@pytest.fixture()
def example_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def client(example_root: Path) -> TestClient:
    return TestClient(create_app(example_root))


def save_payload() -> dict:
    return {
        "credentials": CREDENTIALS,
        "aws": {"profile": "dev", "accountId": "123456789012", "region": "us-east-1"},
        "config": minimal_config_dict(),
    }


def test_index_is_served(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_get_config_reports_nothing_configured_yet(client: TestClient):
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["config"] is None


def test_saving_writes_both_files(client: TestClient, example_root: Path):
    response = client.post("/api/config", json=save_payload())

    assert response.status_code == 200
    assert (example_root / "ivr-config.json").is_file()
    assert (example_root / ".env").is_file()


def test_saving_reports_the_next_command(client: TestClient):
    response = client.post("/api/config", json=save_payload())
    assert "make deploy" in response.json()["nextCommand"]


def test_saving_puts_credentials_in_env_not_in_the_config_file(
    client: TestClient, example_root: Path
):
    client.post("/api/config", json=save_payload())

    config_text = (example_root / "ivr-config.json").read_text()
    env_text = (example_root / ".env").read_text()

    assert "api-secret" not in config_text
    assert "TWILIO_API_SECRET=api-secret" in env_text


def test_saving_generates_a_session_token(client: TestClient, example_root: Path):
    client.post("/api/config", json=save_payload())
    env_text = (example_root / ".env").read_text()

    tokens = [
        line.split("=", 1)[1]
        for line in env_text.splitlines()
        if line.startswith("IVR_SESSION_TOKEN=")
    ]
    assert len(tokens) == 1
    assert len(tokens[0]) >= 32


def test_saving_twice_keeps_the_same_session_token(client: TestClient, example_root: Path):
    client.post("/api/config", json=save_payload())
    first = (example_root / ".env").read_text()

    client.post("/api/config", json=save_payload())
    second = (example_root / ".env").read_text()

    def token(text: str) -> str:
        return next(line for line in text.splitlines() if line.startswith("IVR_SESSION_TOKEN="))

    assert token(first) == token(second)


def test_saving_rejects_an_invalid_config(client: TestClient, example_root: Path):
    payload = save_payload()
    payload["config"]["intents"] = []

    response = client.post("/api/config", json=payload)

    assert response.status_code == 422
    assert not (example_root / "ivr-config.json").exists()


def test_saving_rejects_a_duplicate_intent_key(client: TestClient):
    payload = save_payload()
    payload["config"]["intents"].append(dict(payload["config"]["intents"][0]))

    response = client.post("/api/config", json=payload)

    assert response.status_code == 422


def test_get_config_returns_the_saved_config_with_secrets_redacted(
    client: TestClient, example_root: Path
):
    client.post("/api/config", json=save_payload())

    body = client.get("/api/config").json()

    assert body["config"]["business"]["name"] == "Owl Insurance"
    assert body["env"]["TWILIO_API_SECRET"] == "•••• set"
    assert body["env"]["AWS_REGION"] == "us-east-1"


def test_resources_endpoint_surfaces_a_credential_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    def boom(credentials):
        raise RuntimeError("Authentication failed")

    monkeypatch.setattr("wizard.server.verify", boom)

    response = client.post("/api/resources", json=CREDENTIALS)

    assert response.status_code == 400
    assert "Authentication failed" in response.json()["detail"]


def test_resources_endpoint_returns_numbers_and_configurations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("wizard.server.verify", lambda credentials: "Test Account")
    monkeypatch.setattr(
        "wizard.server.list_phone_numbers",
        lambda credentials: [{"sid": "PN1", "phoneNumber": "+15550000000", "friendlyName": "Main"}],
    )
    monkeypatch.setattr(
        "wizard.server.list_conversation_configurations",
        lambda credentials: [{"id": "WR1", "displayName": "Default"}],
    )

    body = client.post("/api/resources", json=CREDENTIALS).json()

    assert body["accountName"] == "Test Account"
    assert body["phoneNumbers"][0]["sid"] == "PN1"
    assert body["conversationConfigurations"][0]["id"] == "WR1"


# --- error explanation ------------------------------------------------------


def test_explain_20003_names_the_api_key_not_the_auth_token():
    """Error 20003 must point at the credentials actually used.

    /api/resources authenticates with the API Key SID and Secret, so a message
    that just echoes Twilio's "Unable to fetch record: Authenticate" leaves the
    user checking the wrong field.
    """
    from twilio.base.exceptions import TwilioRestException
    from wizard.server import explain_twilio_failure

    message = explain_twilio_failure(
        TwilioRestException(401, "/Accounts/ACxxx.json", "Unable to fetch record", 20003, "GET")
    )

    assert "20003" in message
    assert "API Key Secret" in message
    assert "shown only once" in message


def test_explain_does_not_echo_the_request_uri():
    """The raw exception string embeds the request path; the reply should not."""
    from twilio.base.exceptions import TwilioRestException
    from wizard.server import explain_twilio_failure

    sid = "AC" + "9" * 32
    message = explain_twilio_failure(
        TwilioRestException(401, f"/Accounts/{sid}.json", "Unable to fetch record", 20003, "GET")
    )

    assert sid not in message


def test_explain_distinguishes_a_control_plane_rejection():
    """A Conversations Control Plane 403 is a different fix from a bad API key."""
    import httpx
    from wizard.server import explain_twilio_failure

    request = httpx.Request(
        "GET", "https://conversations.twilio.com/v2/ControlPlane/Configurations"
    )
    response = httpx.Response(403, request=request)

    message = explain_twilio_failure(
        httpx.HTTPStatusError("forbidden", request=request, response=response)
    )

    assert "Conversation Orchestrator" in message
    assert "403" in message


def test_explain_reports_a_network_failure_as_such():
    import httpx
    from wizard.server import explain_twilio_failure

    message = explain_twilio_failure(httpx.ConnectError("connection refused"))

    assert "Could not reach Twilio" in message


def test_resources_endpoint_returns_the_explained_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """The 400 detail carries the explanation, not the raw exception string."""
    from twilio.base.exceptions import TwilioRestException

    def boom(credentials):
        raise TwilioRestException(
            401, "/Accounts/ACxxx.json", "Unable to fetch record", 20003, "GET"
        )

    monkeypatch.setattr("wizard.server.verify", boom)

    response = client.post("/api/resources", json=CREDENTIALS)

    assert response.status_code == 400
    assert "API Key Secret" in response.json()["detail"]


# --- verify() uses the Standard-key-safe endpoint ---------------------------


def _account(sid: str, friendly_name: str | None):
    from unittest.mock import MagicMock

    account = MagicMock()
    account.sid = sid
    account.friendly_name = friendly_name
    return account


def test_verify_lists_accounts_rather_than_fetching_one():
    """``/Accounts/{sid}`` needs a **Main** API key; the list works with Standard.

    Requiring a Main key just to populate two dropdowns would be a bad trade, so
    verify() must call accounts.list, not accounts(sid).fetch.
    """
    from unittest.mock import patch

    from wizard.twilio_lookup import TwilioCredentials, verify

    sid = "AC" + "1" * 32
    creds = TwilioCredentials(
        accountSid=sid, authToken="t", apiKey="SK" + "2" * 32, apiSecret="s" * 32
    )

    with patch("wizard.twilio_lookup.Client") as client:
        accounts = client.return_value.api.v2010.accounts
        accounts.list.return_value = [_account(sid, "My Account")]

        assert verify(creds) == "My Account"

        accounts.list.assert_called_once_with(limit=20)
        accounts.assert_not_called()  # i.e. no accounts(sid).fetch()


def test_verify_rejects_a_key_that_cannot_see_the_entered_account():
    """A key for another account must fail loudly, not silently misconfigure."""
    from unittest.mock import patch

    from wizard.twilio_lookup import AccountMismatchError, TwilioCredentials, verify

    creds = TwilioCredentials(
        accountSid="AC" + "1" * 32, authToken="t", apiKey="SK" + "2" * 32, apiSecret="s" * 32
    )
    other = "AC" + "9" * 32

    with patch("wizard.twilio_lookup.Client") as client:
        client.return_value.api.v2010.accounts.list.return_value = [_account(other, "Other")]

        with pytest.raises(AccountMismatchError) as excinfo:
            verify(creds)

    assert other in str(excinfo.value)


def test_verify_falls_back_to_the_sid_when_there_is_no_friendly_name():
    from unittest.mock import patch

    from wizard.twilio_lookup import TwilioCredentials, verify

    sid = "AC" + "1" * 32
    creds = TwilioCredentials(
        accountSid=sid, authToken="t", apiKey="SK" + "2" * 32, apiSecret="s" * 32
    )

    with patch("wizard.twilio_lookup.Client") as client:
        client.return_value.api.v2010.accounts.list.return_value = [_account(sid, None)]

        assert verify(creds) == sid


def test_explain_20003_does_not_claim_a_main_key_is_needed():
    """A Standard key is sufficient now that verify() lists accounts."""
    from twilio.base.exceptions import TwilioRestException
    from wizard.server import explain_twilio_failure

    message = explain_twilio_failure(
        TwilioRestException(401, "/Accounts.json", "Authenticate", 20003, "GET")
    )

    assert "Standard key is sufficient" in message
    assert "Standard key is required" not in message
