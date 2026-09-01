"""Studio widget type identifiers and property names.

The types below other than ConversationRelay come from Twilio's published widget
JSON schemas: https://www.twilio.com/docs/studio/rest-api/v2/schemas

ConversationRelay shipped in March 2026 and is not in those schemas, so its type
string and property names are pinned here in one place rather than scattered
through the flow builder.

**``CR_WIDGET_TYPE``, ``CR_URL_PROPERTY`` and ``CR_VOICE_PROPERTY_MAP`` are
UNVERIFIED.** They are
educated guesses; no probe has been run against a real Twilio account. Run
``python -m studio.discover`` with credentials to confirm or correct the type
string, and build a ConversationRelay widget in the Studio Console and fetch the
flow definition to confirm the property names. Until then the failure mode is a
400 from the Flows API when the generated flow is published — loud, not silent.
"""

from __future__ import annotations

TRIGGER_TYPE = "trigger"
HTTP_REQUEST_TYPE = "make-http-request"
CONNECT_CALL_TYPE = "connect-call-to"
SPLIT_TYPE = "split-based-on"
TWIML_REDIRECT_TYPE = "add-twiml-redirect"
SAY_PLAY_TYPE = "say-play"

#: UNVERIFIED guess — run studio/discover.py with credentials to confirm.
CR_WIDGET_TYPE = "conversationrelay"

#: Candidates tried by the discovery probe, in order.
CR_WIDGET_TYPE_CANDIDATES = (
    "conversationrelay",
    "run-conversationrelay",
    "connect-conversationrelay",
    "add-conversationrelay",
    "conversation-relay",
)

#: Property holding the wss:// endpoint on the ConversationRelay widget.
#: UNVERIFIED — confirm via a Console-built widget fetch.
CR_URL_PROPERTY = "url"

#: Maps IVRConfig.voice field names to ConversationRelay widget property names.
CR_VOICE_PROPERTY_MAP = {
    "language": "language",
    "tts_provider": "tts_provider",
    "voice": "voice",
    "transcription_provider": "transcription_provider",
    "speech_model": "speech_model",
}
