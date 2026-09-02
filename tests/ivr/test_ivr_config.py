"""Tests for the IVR configuration model and loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ivr_config import (
    ClientDestination,
    IVRConfig,
    PhoneDestination,
    SipDestination,
    load_config,
)
from pydantic import ValidationError


def minimal_config_dict() -> dict:
    """A valid config with one phone intent, using JSON aliases."""
    return {
        "version": 1,
        "business": {
            "name": "Owl Insurance",
            "prompt": "Owl Insurance sells home and auto policies.",
            "greeting": "Thanks for calling Owl Insurance.",
        },
        "intents": [
            {
                "key": "billing",
                "name": "Billing",
                "description": "Invoices and payments.",
                "destination": {"type": "phone", "number": "+15551230001"},
            }
        ],
        "fallback": {
            "name": "Operator",
            "description": "Anything else.",
            "destination": {"type": "phone", "number": "+15551230000"},
        },
        "twilio": {
            "phoneNumber": "+15550000000",
            "phoneNumberSid": "PN" + "a" * 32,
            "conversationConfigurationId": "WR123",
        },
    }


def test_minimal_config_validates():
    config = IVRConfig.model_validate(minimal_config_dict())
    assert config.intent_keys == ["billing"]
    assert config.business.name == "Owl Insurance"


def test_destination_union_discriminates_by_type():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"] = {"type": "sip", "uri": "sip:sales@pbx.example.com"}
    raw["fallback"]["destination"] = {"type": "client", "identity": "operator"}
    config = IVRConfig.model_validate(raw)
    assert isinstance(config.intents[0].destination, SipDestination)
    assert isinstance(config.fallback.destination, ClientDestination)


def test_send_digits_encodes_pause_as_half_second_w_characters():
    destination = PhoneDestination(number="+15551230001", extension="402")
    assert destination.send_digits == "wwww402"


def test_send_digits_honours_custom_pause():
    destination = PhoneDestination(number="+15551230001", extension="402", extensionPauseSeconds=1)
    assert destination.send_digits == "ww402"


def test_send_digits_is_none_without_an_extension():
    assert PhoneDestination(number="+15551230001").send_digits is None


def test_sip_dial_target_appends_encoded_headers():
    destination = SipDestination(
        uri="sip:sales@pbx.example.com", headers={"X-Dept": "new business"}
    )
    assert destination.dial_target == "sip:sales@pbx.example.com?X-Dept=new+business"


def test_sip_dial_target_is_unchanged_without_headers():
    destination = SipDestination(uri="sip:sales@pbx.example.com")
    assert destination.dial_target == "sip:sales@pbx.example.com"


def test_sip_headers_must_use_the_x_prefix_twilio_requires():
    with pytest.raises(ValidationError, match="X-"):
        SipDestination(uri="sip:sales@pbx.example.com", headers={"Dept": "sales"})


def test_sip_uri_accepts_bare_domain_uri():
    """A trunk URI with no user-info component must be accepted (Finding 5)."""
    dest = SipDestination(uri="sip:pbx.example.com")
    assert dest.uri == "sip:pbx.example.com"


def test_sip_uri_accepts_sips_scheme():
    dest = SipDestination(uri="sips:secure@pbx.example.com")
    assert dest.uri == "sips:secure@pbx.example.com"


def test_sip_uri_rejects_non_sip_string():
    """A non-SIP URI must still be rejected."""
    with pytest.raises(ValidationError):
        SipDestination(uri="https://pbx.example.com")


def test_rejects_non_e164_phone_number():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"]["number"] = "555-1234"
    with pytest.raises(ValidationError):
        IVRConfig.model_validate(raw)


def test_rejects_duplicate_intent_keys():
    raw = minimal_config_dict()
    raw["intents"].append(dict(raw["intents"][0]))
    with pytest.raises(ValidationError, match="duplicate intent keys"):
        IVRConfig.model_validate(raw)


def test_rejects_reserved_fallback_key():
    raw = minimal_config_dict()
    raw["intents"][0]["key"] = "fallback"
    with pytest.raises(ValidationError, match="reserved"):
        IVRConfig.model_validate(raw)


def test_rejects_empty_intent_list():
    raw = minimal_config_dict()
    raw["intents"] = []
    with pytest.raises(ValidationError):
        IVRConfig.model_validate(raw)


def test_rejects_over_length_business_prompt():
    raw = minimal_config_dict()
    raw["business"]["prompt"] = "x" * 4001
    with pytest.raises(ValidationError):
        IVRConfig.model_validate(raw)


def test_extension_destinations_only_includes_intents_needing_dtmf():
    raw = minimal_config_dict()
    raw["intents"][0]["destination"]["extension"] = "402"
    raw["intents"].append(
        {
            "key": "sales",
            "name": "Sales",
            "description": "Quotes.",
            "destination": {"type": "phone", "number": "+15551230002"},
        }
    )
    config = IVRConfig.model_validate(raw)
    assert config.extension_destinations() == {
        "billing": {"number": "+15551230001", "sendDigits": "wwww402"}
    }


def test_extension_destinations_includes_the_fallback_when_it_has_an_extension():
    raw = minimal_config_dict()
    raw["fallback"]["destination"]["extension"] = "0"
    config = IVRConfig.model_validate(raw)
    assert config.extension_destinations() == {
        "fallback": {"number": "+15551230000", "sendDigits": "wwww0"}
    }


def test_load_config_reads_an_explicit_path(tmp_path: Path):
    target = tmp_path / "ivr-config.json"
    target.write_text(json.dumps(minimal_config_dict()))
    assert load_config(target).business.name == "Owl Insurance"


def test_load_config_reports_where_it_looked(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="make configure"):
        load_config(tmp_path / "missing.json")
