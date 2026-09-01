"""System prompt assembly for the IVR agent.

The voice prompt turns the agent into a triage attendant whose only job is to
pick one configured destination and call ``transfer_call``. The SMS prompt shares
the same business context but has no transfer tool, so it points callers at the
phone number instead.
"""

from __future__ import annotations

from ivr_config import FALLBACK_KEY, IVRConfig

VOICE_RULES = """\
You are the automated phone attendant for {business_name}.

Your only job is to work out which department the caller needs, then transfer them.

How to speak:
- One or two short sentences per turn. This is a phone call, not a chat window.
- Never use markdown, asterisks, bullet points, or emoji. Everything you say is read aloud.
- Ask at most one question per turn.

How to route:
- Match the caller to exactly one option from the list below.
- Once you know the option, say one short sentence naming where you are sending them, then \
call the transfer_call tool in the same turn. Do not ask the caller to confirm first.
- If the caller is vague, ask one clarifying question. If you still cannot tell after two \
attempts, transfer to {fallback_name}.
- If the caller asks for a person, a manager, or an operator, transfer to {fallback_name} \
straight away.
- Never invent a department that is not listed, and never promise a callback or anything \
else you cannot do.
- Do not try to solve the caller's problem, quote prices, or give policy details. Route them.
"""

SMS_RULES = """\
You are the messaging assistant for {business_name}.

- Keep replies to two or three sentences.
- Never use markdown, asterisks, bullet points, or emoji.
- Answer what you can from the information below.
- If the caller needs a department, tell them to call {phone_number} and say what to ask for.
- Never invent policy details, prices, or promises.
"""


def render_intent_catalog(config: IVRConfig) -> str:
    """Render the routable options, including the fallback, for the system prompt."""
    lines = ["Options you can transfer to:"]
    for intent in config.intents:
        lines.append(f"- {intent.key}: {intent.name} — {intent.description}")
    lines.append(f"- {FALLBACK_KEY}: {config.fallback.name} — {config.fallback.description}")
    return "\n".join(lines)


def _business_section(config: IVRConfig) -> str:
    return f"About {config.business.name}:\n{config.business.prompt}"


def build_voice_system_prompt(config: IVRConfig) -> str:
    """Build the system prompt for the voice (IVR) agent."""
    return "\n".join(
        [
            VOICE_RULES.format(
                business_name=config.business.name,
                fallback_name=config.fallback.name,
            ),
            _business_section(config),
            "",
            render_intent_catalog(config),
        ]
    )


def build_sms_system_prompt(config: IVRConfig) -> str:
    """Build the system prompt for the SMS agent, which has no transfer tool."""
    return "\n".join(
        [
            SMS_RULES.format(
                business_name=config.business.name,
                phone_number=config.twilio.phone_number,
            ),
            _business_section(config),
            "",
            render_intent_catalog(config),
        ]
    )
