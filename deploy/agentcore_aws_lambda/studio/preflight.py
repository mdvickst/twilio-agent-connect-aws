"""Verify the Conversation Orchestrator capture rules the voice path depends on.

Studio's ConversationRelay widget cannot set ``conversationConfiguration``, so
Orchestrator has to capture traffic for the IVR number passively. If it does not,
TAC's voice channel polls for a conversation keyed on the CallSid, gives up after
about 3.75 seconds, and the caller silently drops through to the operator.

Checking at deploy time turns that into an actionable error.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ivr_config import IVRConfig, load_config

if TYPE_CHECKING:
    from tac.models.conversation import (
        CaptureRule,
        ChannelSettings,
        ConversationConfiguration,
    )

REQUIRED_CHANNELS = ("VOICE", "SMS")

WILDCARD = "*"


def rule_matches(rule: CaptureRule, number: str) -> bool:
    """True if ``rule`` captures traffic addressed to ``number``."""
    return rule.to_address in (number, WILDCARD)


def find_channel_settings(
    channel_settings: dict[str, ChannelSettings] | None, channel: str
) -> ChannelSettings | None:
    """Look up a channel's settings, ignoring key casing."""
    if not channel_settings:
        return None
    for key, settings in channel_settings.items():
        if key.upper() == channel.upper():
            return settings
    return None


def check_capture_rules(
    configuration: ConversationConfiguration,
    number: str,
    channels: Iterable[str] = REQUIRED_CHANNELS,
) -> list[str]:
    """Return one problem string per channel missing a matching capture rule.

    Args:
        configuration: The Conversation Orchestrator configuration to inspect.
        number: The IVR phone number in E.164.
        channels: Channels that must capture traffic for this number.

    Returns:
        Human-readable problems. Empty means the configuration is healthy.
    """
    problems: list[str] = []
    for channel in channels:
        settings = find_channel_settings(configuration.channel_settings, channel)
        rules = settings.capture_rules if settings else None
        if not rules:
            problems.append(
                f"{channel} has no capture rules, so Conversation Orchestrator will "
                f"not create conversations for {number}."
            )
            continue
        if not any(rule_matches(rule, number) for rule in rules):
            configured = ", ".join(rule.to_address for rule in rules) or "none"
            problems.append(
                f"{channel} has capture rules, but none match {number} "
                f"(configured destinations: {configured})."
            )
    return problems


def format_problems(problems: list[str], config: IVRConfig) -> str:
    """Turn problems into a message that says exactly what to fix."""
    bullets = "\n".join(f"  - {problem}" for problem in problems)
    return (
        "Conversation Orchestrator is not capturing traffic for this IVR:\n"
        f"{bullets}\n\n"
        "Fix it in the Twilio Console:\n"
        f"  1. Open Conversation Orchestrator configuration "
        f"{config.twilio.conversation_configuration_id}.\n"
        "  2. Go to the Channel Traffic tab.\n"
        "  3. Under 'Automatically captured traffic', add "
        f"{config.twilio.phone_number} for both Voice and Messaging.\n\n"
        "Or run 'make capture-rules' to add them for you.\n\n"
        "Why this matters: the Studio ConversationRelay widget cannot set "
        "conversationConfiguration, so passive capture is what creates the "
        "conversation TAC looks up by CallSid. Without it every call falls through "
        "to the fallback destination."
    )


def fetch_configuration(config: IVRConfig) -> ConversationConfiguration:
    """Read the Orchestrator configuration this IVR points at.

    Builds a TAC instance from the environment because TAC's Orchestrator client
    is the only reader for the Control Plane configuration endpoint in this repo.

    Raises:
        RuntimeError: If credentials are missing or Orchestrator is unavailable.
    """
    from tac import TAC
    from tac.core.config import TACConfig

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    api_key = os.environ.get("TWILIO_API_KEY")
    api_secret = os.environ.get("TWILIO_API_SECRET")
    if not (account_sid and api_key and api_secret):
        raise RuntimeError("Set TWILIO_ACCOUNT_SID, TWILIO_API_KEY and TWILIO_API_SECRET.")

    tac = TAC(
        config=TACConfig(
            account_sid=account_sid,
            auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
            api_key=api_key,
            api_secret=api_secret,
            phone_number=config.twilio.phone_number,
            conversation_configuration_id=config.twilio.conversation_configuration_id,
        )
    )
    orchestrator = tac.conversation_orchestrator_client
    if orchestrator is None:
        raise RuntimeError("Conversation Orchestrator client is unavailable.")

    return orchestrator.get_configuration(config.twilio.conversation_configuration_id)


def run_check(config: IVRConfig) -> list[str]:
    """Fetch the configuration and check it. Returns problems, empty when healthy."""
    return check_capture_rules(fetch_configuration(config), config.twilio.phone_number)


def main() -> int:
    """CLI entry point for ``make preflight``."""
    config = load_config()
    print("Checking Conversation Orchestrator capture rules...")
    try:
        problems = run_check(config)
    except Exception as error:
        print(f"  Could not read the configuration: {error}", file=sys.stderr)
        return 1

    if problems:
        print(format_problems(problems, config), file=sys.stderr)
        return 1

    print(f"  OK: traffic for {config.twilio.phone_number} is captured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
