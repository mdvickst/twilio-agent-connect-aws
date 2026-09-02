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

``CR_WIDGET_TYPE`` is set to ``"run-conversationrelay"`` based on three signals:

1. The documentation URL is ``/studio/widget-library/run-conversationrelay``.
2. The docs' Liquid example uses the default widget name ``run_crelay_1`` —
   Studio derives default instance names from the type slug.
3. Every other action widget in the schema is verb-prefixed and hyphenated
   (``run-function``, ``make-http-request``, ``add-twiml-redirect``,
   ``connect-call-to``).

These are still UNVERIFIED — confirm with ``python -m studio.discover``.
"""

from __future__ import annotations

TRIGGER_TYPE = "trigger"
HTTP_REQUEST_TYPE = "make-http-request"
CONNECT_CALL_TYPE = "connect-call-to"
SPLIT_TYPE = "split-based-on"
TWIML_REDIRECT_TYPE = "add-twiml-redirect"
SAY_PLAY_TYPE = "say-play"

#: UNVERIFIED guess — run studio/discover.py with credentials to confirm.
#: Set to "run-conversationrelay" based on the doc URL, default instance name,
#: and the verb-prefixed naming pattern of all other action widgets; see module
#: docstring for full reasoning.
CR_WIDGET_TYPE = "run-conversationrelay"

#: Candidates tried by the discovery probe, in order.
CR_WIDGET_TYPE_CANDIDATES = (
    "run-conversationrelay",
    "conversationrelay",
    "connect-conversationrelay",
    "add-conversationrelay",
    "conversation-relay",
)

#: Property holding the wss:// endpoint on the ConversationRelay widget.
#: UNVERIFIED — confirm via a Console-built widget fetch.
CR_URL_PROPERTY = "url"

#: Maps IVRConfig.voice field names to ConversationRelay widget property names.
#: UNVERIFIED — confirm field names via a Console-built widget fetch.
#: "language" maps to "language_code" because the widget's documented field is
#: "Language Code" (not bare "language").
CR_VOICE_PROPERTY_MAP = {
    "language": "language_code",
    "tts_provider": "tts_provider",
    "voice": "voice",
    "transcription_provider": "transcription_provider",
    "speech_model": "speech_model",
}
