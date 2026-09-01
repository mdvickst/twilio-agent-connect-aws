"""Tests for Studio flow provisioning."""

from __future__ import annotations

from typing import Any

import pytest
from studio.capture_rules import add_capture_rules
from studio.provision import attach_number, find_flow_by_name, lambda_url_from_env, upsert_flow


class FakeFlow:
    def __init__(self, sid: str, friendly_name: str) -> None:
        self.sid = sid
        self.friendly_name = friendly_name
        self.webhook_url = f"https://webhooks.twilio.com/v1/Accounts/AC1/Flows/{sid}"
        self.updated_with: dict[str, Any] | None = None

    def update(self, **kwargs: Any) -> FakeFlow:
        self.updated_with = kwargs
        return self


class FakeFlowList:
    def __init__(self, existing: list[FakeFlow]) -> None:
        self.existing = existing
        self.created_with: dict[str, Any] | None = None

    def list(self) -> list[FakeFlow]:
        return self.existing

    def create(self, **kwargs: Any) -> FakeFlow:
        self.created_with = kwargs
        flow = FakeFlow("FWnew", kwargs["friendly_name"])
        self.existing.append(flow)
        return flow

    def __call__(self, sid: str) -> FakeFlow:
        return next(flow for flow in self.existing if flow.sid == sid)


class FakeNumber:
    def __init__(self) -> None:
        self.updated_with: dict[str, Any] | None = None

    def update(self, **kwargs: Any) -> None:
        self.updated_with = kwargs


class FakeClient:
    def __init__(self, existing: list[FakeFlow] | None = None) -> None:
        self.flow_list = FakeFlowList(existing or [])
        self.number = FakeNumber()

        studio_v2 = type("V2", (), {"flows": self.flow_list})()
        self.studio = type("Studio", (), {"v2": studio_v2})()

    def incoming_phone_numbers(self, sid: str) -> FakeNumber:
        self.number.sid = sid
        return self.number


DEFINITION = {"description": "x", "initial_state": "Trigger", "states": [], "flags": {}}


def test_find_flow_returns_none_when_absent():
    client = FakeClient()
    assert find_flow_by_name(client, "TAC AI IVR — Owl Insurance") is None


def test_find_flow_matches_on_friendly_name():
    existing = FakeFlow("FW1", "TAC AI IVR — Owl Insurance")
    client = FakeClient([existing])
    assert find_flow_by_name(client, "TAC AI IVR — Owl Insurance") is existing


def test_upsert_creates_a_published_flow_when_absent():
    client = FakeClient()
    flow = upsert_flow(client, "TAC AI IVR — Owl Insurance", DEFINITION)

    assert client.flow_list.created_with["status"] == "published"
    assert client.flow_list.created_with["definition"] == DEFINITION
    assert flow.sid == "FWnew"


def test_upsert_updates_in_place_when_the_flow_already_exists():
    existing = FakeFlow("FW1", "TAC AI IVR — Owl Insurance")
    client = FakeClient([existing])

    flow = upsert_flow(client, "TAC AI IVR — Owl Insurance", DEFINITION)

    assert client.flow_list.created_with is None
    assert existing.updated_with["status"] == "published"
    assert existing.updated_with["definition"] == DEFINITION
    assert existing.updated_with["commit_message"]
    assert flow.sid == "FW1"


def test_upsert_records_a_commit_message():
    client = FakeClient()
    upsert_flow(client, "TAC AI IVR — Owl Insurance", DEFINITION)
    assert client.flow_list.created_with["commit_message"]


def test_attach_number_points_the_voice_webhook_at_the_flow():
    client = FakeClient()
    attach_number(client, "PN" + "a" * 32, "https://webhooks.twilio.com/v1/x")

    assert client.number.updated_with == {
        "voice_url": "https://webhooks.twilio.com/v1/x",
        "voice_method": "POST",
    }


def test_add_capture_rules_creates_both_channels_from_nothing():
    updated = add_capture_rules({}, "+15550000000")
    assert updated["channelSettings"]["VOICE"]["captureRules"] == [
        {"from": "*", "to": "+15550000000"}
    ]
    assert updated["channelSettings"]["SMS"]["captureRules"] == [
        {"from": "*", "to": "+15550000000"}
    ]


def test_add_capture_rules_preserves_existing_rules():
    existing = {
        "channelSettings": {
            "VOICE": {"captureRules": [{"from": "*", "to": "+15559999999"}]},
        }
    }
    updated = add_capture_rules(existing, "+15550000000")
    assert updated["channelSettings"]["VOICE"]["captureRules"] == [
        {"from": "*", "to": "+15559999999"},
        {"from": "*", "to": "+15550000000"},
    ]


def test_add_capture_rules_is_idempotent():
    once = add_capture_rules({}, "+15550000000")
    twice = add_capture_rules(once, "+15550000000")
    assert twice["channelSettings"]["VOICE"]["captureRules"] == [
        {"from": "*", "to": "+15550000000"}
    ]


def test_add_capture_rules_respects_a_wildcard_rule():
    existing = {"channelSettings": {"VOICE": {"captureRules": [{"from": "*", "to": "*"}]}}}
    updated = add_capture_rules(existing, "+15550000000")
    assert updated["channelSettings"]["VOICE"]["captureRules"] == [{"from": "*", "to": "*"}]


def test_add_capture_rules_does_not_mutate_its_input():
    original = {"channelSettings": {"VOICE": {"captureRules": []}}}
    add_capture_rules(original, "+15550000000")
    assert original["channelSettings"]["VOICE"]["captureRules"] == []


# ---------------------------------------------------------------------------
# lambda_url_from_env — IVR_LAMBDA_URL branch (no subprocess needed)
# ---------------------------------------------------------------------------


def test_lambda_url_from_env_one_path_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IVR_LAMBDA_URL", "https://abc.lambda-url.us-east-1.on.aws/twiml")
    assert lambda_url_from_env() == "https://abc.lambda-url.us-east-1.on.aws"


def test_lambda_url_from_env_no_path_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Previously returned 'https:/' due to rsplit; now returns the correct base."""
    monkeypatch.setenv("IVR_LAMBDA_URL", "https://abc.lambda-url.us-east-1.on.aws")
    assert lambda_url_from_env() == "https://abc.lambda-url.us-east-1.on.aws"


def test_lambda_url_from_env_two_path_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IVR_LAMBDA_URL", "https://abc.lambda-url.us-east-1.on.aws/twilio/voice")
    assert lambda_url_from_env() == "https://abc.lambda-url.us-east-1.on.aws"


def test_lambda_url_from_env_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IVR_LAMBDA_URL", "https://abc.lambda-url.us-east-1.on.aws/")
    assert lambda_url_from_env() == "https://abc.lambda-url.us-east-1.on.aws"


def test_lambda_url_from_env_non_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IVR_LAMBDA_URL", "not a url")
    with pytest.raises(RuntimeError):
        lambda_url_from_env()
