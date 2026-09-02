"""Studio widget type identifiers and property names.

The types below other than ConversationRelay come from Twilio's published widget
JSON schemas: https://www.twilio.com/docs/studio/rest-api/v2/schemas

ConversationRelay shipped in March 2026 and is not in those schemas, so its type
string and property names are pinned here in one place rather than scattered
through the flow builder.

**``CR_WIDGET_TYPE`` and ``CR_URL_PROPERTY`` are CONFIRMED** against a live
account via ``POST /v2/Flows/Validate`` (2026-09-02):

- The validator's own type enumeration contains ``run-conversation-relay``.
  Note the hyphen between "conversation" and "relay" — neither
  ``conversationrelay`` nor ``run-conversationrelay`` is accepted.
- ``url`` is required on this widget: renaming or removing it is rejected with
  ``#/states/N/properties/url is missing but it is required``.

**``CR_VOICE_PROPERTY_MAP`` remains UNVERIFIED**, and validation cannot settle
it: the validator silently ACCEPTS unknown properties (a deliberately bogus key
validates), so a wrong optional name here fails *silently* — the setting is
ignored at runtime and the caller just gets Twilio's defaults. It cannot cause a
400. To confirm, build a ConversationRelay widget in the Studio Console with
these fields set and fetch the flow definition:

    twilio api:studio:v2:flows:fetch --sid FWxxxx -o json

The names below follow the pattern the confirmed values establish: a Studio
property is the snake_case form of the underlying TwiML attribute — ``url`` from
``url``, and in ``connect-call-to``, ``caller_id`` from ``callerId`` and
``time_limit`` from ``timeLimit``. ``<ConversationRelay>``'s attribute is
``language``, so ``language`` is used rather than ``language_code`` (the docs
page labels the *UI field* "Language Code", which is not the property name).
"""

from __future__ import annotations

TRIGGER_TYPE = "trigger"
HTTP_REQUEST_TYPE = "make-http-request"
CONNECT_CALL_TYPE = "connect-call-to"
SPLIT_TYPE = "split-based-on"
TWIML_REDIRECT_TYPE = "add-twiml-redirect"
SAY_PLAY_TYPE = "say-play"

#: CONFIRMED 2026-09-02 against POST /v2/Flows/Validate, whose type enumeration
#: contains exactly this string. Mind the hyphen: "run-conversationrelay" is
#: rejected, as is "conversationrelay".
CR_WIDGET_TYPE = "run-conversation-relay"

#: Candidates tried by the discovery probe, in order.
CR_WIDGET_TYPE_CANDIDATES = (
    "run-conversation-relay",
    "run-conversationrelay",
    "conversationrelay",
    "connect-conversationrelay",
    "add-conversationrelay",
    "conversation-relay",
)

#: Property holding the wss:// endpoint. CONFIRMED required — the validator
#: rejects the definition if it is renamed or absent.
CR_URL_PROPERTY = "url"

#: Maps IVRConfig.voice field names to ConversationRelay widget property names.
#: STILL UNVERIFIED, and validation cannot confirm these: unknown optional
#: properties are silently accepted, so a wrong name here is ignored at runtime
#: rather than rejected. See the module docstring for how to settle it.
CR_VOICE_PROPERTY_MAP = {
    "language": "language",
    "tts_provider": "tts_provider",
    "voice": "voice",
    "transcription_provider": "transcription_provider",
    "speech_model": "speech_model",
}
