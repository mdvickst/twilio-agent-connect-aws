"""Tests for the Conversation Orchestrator capture-rule preflight."""

from __future__ import annotations

from ivr_config import IVRConfig
from studio.preflight import check_capture_rules, format_problems, rule_matches
from tac.models.conversation import CaptureRule, ChannelSettings, ConversationConfiguration

from tests.ivr.test_ivr_config import minimal_config_dict

NUMBER = "+15550000000"


def configuration(channel_settings: dict[str, ChannelSettings] | None) -> ConversationConfiguration:
    return ConversationConfiguration(
        id="WR123",
        description="Test configuration",
        conversationGroupingType="GROUP_BY_PROFILE",
        memoryStoreId="store_1",
        channelSettings=channel_settings,
    )


def settings_with(*rules: CaptureRule) -> ChannelSettings:
    return ChannelSettings(captureRules=list(rules))


def healthy_settings() -> dict[str, ChannelSettings]:
    rule = CaptureRule(**{"from": "*", "to": NUMBER})
    return {"VOICE": settings_with(rule), "SMS": settings_with(rule)}


def test_rule_matches_an_exact_number():
    assert rule_matches(CaptureRule(**{"from": "*", "to": NUMBER}), NUMBER)


def test_rule_matches_a_wildcard_destination():
    assert rule_matches(CaptureRule(**{"from": "*", "to": "*"}), NUMBER)


def test_rule_does_not_match_a_different_number():
    assert not rule_matches(CaptureRule(**{"from": "*", "to": "+15559999999"}), NUMBER)


def test_healthy_configuration_reports_no_problems():
    assert check_capture_rules(configuration(healthy_settings()), NUMBER) == []


def test_channel_keys_match_case_insensitively():
    rule = CaptureRule(**{"from": "*", "to": NUMBER})
    lowercase = {"voice": settings_with(rule), "sms": settings_with(rule)}
    assert check_capture_rules(configuration(lowercase), NUMBER) == []


def test_missing_voice_channel_is_reported():
    rule = CaptureRule(**{"from": "*", "to": NUMBER})
    problems = check_capture_rules(configuration({"SMS": settings_with(rule)}), NUMBER)
    assert len(problems) == 1
    assert "VOICE" in problems[0]


def test_channel_with_no_rules_is_reported():
    rule = CaptureRule(**{"from": "*", "to": NUMBER})
    channel_settings = {"VOICE": ChannelSettings(captureRules=None), "SMS": settings_with(rule)}
    problems = check_capture_rules(configuration(channel_settings), NUMBER)
    assert len(problems) == 1
    assert "VOICE" in problems[0]


def test_rule_for_a_different_number_is_reported():
    other = CaptureRule(**{"from": "*", "to": "+15559999999"})
    rule = CaptureRule(**{"from": "*", "to": NUMBER})
    problems = check_capture_rules(
        configuration({"VOICE": settings_with(other), "SMS": settings_with(rule)}), NUMBER
    )
    assert len(problems) == 1
    assert NUMBER in problems[0]


def test_configuration_with_no_channel_settings_reports_every_channel():
    problems = check_capture_rules(configuration(None), NUMBER)
    assert len(problems) == 2


def test_formatted_problems_tell_the_operator_what_to_do():
    config = IVRConfig.model_validate(minimal_config_dict())
    message = format_problems(["VOICE has no capture rule"], config)
    assert "VOICE has no capture rule" in message
    assert "Channel Traffic" in message
    assert config.twilio.conversation_configuration_id in message
