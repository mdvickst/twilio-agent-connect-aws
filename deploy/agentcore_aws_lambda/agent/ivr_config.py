"""IVR configuration model and loader.

Canonical home for the schema shared by three consumers: the AgentCore agent
bundle (which builds its prompt and tool from it), the local wizard (which
writes it), and the Studio flow generator (which compiles it into a flow).

This module ships inside the AgentCore code bundle, so it must import with only
pydantic available — no boto3, no twilio, no fastapi.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONFIG_FILENAME = "ivr-config.json"

#: Intent key reserved for the required fallback destination.
FALLBACK_KEY = "fallback"

E164_PATTERN = r"^\+[1-9]\d{1,14}$"
SIP_URI_PATTERN = r"^sips?:\S+"
SIP_HEADER_KEY_PATTERN = r"^X-[A-Za-z0-9-]+$"
EXTENSION_PATTERN = r"^[0-9*#]{1,20}$"
INTENT_KEY_PATTERN = r"^[a-z0-9][a-z0-9_]{0,30}$"
PHONE_NUMBER_SID_PATTERN = r"^PN[0-9a-fA-F]{32}$"


class PhoneDestination(BaseModel):
    """A PSTN number, optionally followed by DTMF digits for an extension."""

    type: Literal["phone"] = "phone"
    number: str = Field(..., pattern=E164_PATTERN)
    extension: str | None = Field(default=None, pattern=EXTENSION_PATTERN)
    extension_pause_seconds: float = Field(default=2.0, ge=0, le=10, alias="extensionPauseSeconds")

    model_config = ConfigDict(populate_by_name=True)

    @property
    def send_digits(self) -> str | None:
        """DTMF string for ``<Number sendDigits>``, or None if there is no extension.

        Each ``w`` is a half-second pause, so the configured pause in seconds
        becomes twice as many ``w`` characters.
        """
        if self.extension is None:
            return None
        return "w" * round(self.extension_pause_seconds * 2) + self.extension


class SipDestination(BaseModel):
    """A SIP endpoint, with optional custom headers and digest credentials."""

    type: Literal["sip"] = "sip"
    uri: str = Field(..., pattern=SIP_URI_PATTERN)
    headers: dict[str, str] = Field(default_factory=dict)
    username: str | None = None
    password: str | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("headers")
    @classmethod
    def _validate_header_keys(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            if not re.match(SIP_HEADER_KEY_PATTERN, key):
                raise ValueError(
                    f"SIP header {key!r} is invalid: Twilio requires custom headers to "
                    f"start with 'X-' and match {SIP_HEADER_KEY_PATTERN}"
                )
        return value

    @property
    def dial_target(self) -> str:
        """The SIP URI with any custom headers appended as URL-encoded parameters."""
        if not self.headers:
            return self.uri
        separator = "&" if "?" in self.uri else "?"
        return f"{self.uri}{separator}{urlencode(self.headers)}"


class ClientDestination(BaseModel):
    """A Twilio Voice SDK client identity."""

    type: Literal["client"] = "client"
    identity: str = Field(..., min_length=1, max_length=121)

    model_config = ConfigDict(populate_by_name=True)


Destination = Annotated[
    PhoneDestination | SipDestination | ClientDestination,
    Field(discriminator="type"),
]


class Business(BaseModel):
    """Customer-supplied description of the business, fed into the system prompt."""

    name: str = Field(..., min_length=1, max_length=100)
    prompt: str = Field(..., min_length=1, max_length=4000)
    greeting: str = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(populate_by_name=True)


class VoiceSettings(BaseModel):
    """ConversationRelay speech settings.

    Every field is optional and omitted from the generated widget when unset, so
    Twilio's own defaults apply rather than values hardcoded here.
    """

    language: str | None = None
    tts_provider: str | None = Field(default=None, alias="ttsProvider")
    voice: str | None = None
    transcription_provider: str | None = Field(default=None, alias="transcriptionProvider")
    speech_model: str | None = Field(default=None, alias="speechModel")

    model_config = ConfigDict(populate_by_name=True)


class Intent(BaseModel):
    """One routable caller intent and where it should be transferred."""

    key: str = Field(..., pattern=INTENT_KEY_PATTERN)
    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field(..., min_length=1, max_length=200)
    destination: Destination

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("key")
    @classmethod
    def _reject_reserved_key(cls, value: str) -> str:
        if value == FALLBACK_KEY:
            raise ValueError(f"intent key {value!r} is reserved for the fallback destination")
        return value


class Fallback(BaseModel):
    """Required destination for callers the agent cannot classify."""

    name: str = Field(default="Operator", min_length=1, max_length=60)
    description: str = Field(
        default="Anything that does not match another option, or the caller asks for a person.",
        min_length=1,
        max_length=200,
    )
    destination: Destination

    model_config = ConfigDict(populate_by_name=True)


class TwilioSettings(BaseModel):
    """The Twilio resources this IVR is attached to."""

    phone_number: str = Field(..., pattern=E164_PATTERN, alias="phoneNumber")
    phone_number_sid: str = Field(..., pattern=PHONE_NUMBER_SID_PATTERN, alias="phoneNumberSid")
    conversation_configuration_id: str = Field(
        ..., min_length=1, alias="conversationConfigurationId"
    )

    model_config = ConfigDict(populate_by_name=True)


class IVRConfig(BaseModel):
    """Everything needed to build the agent prompt, the Studio flow, and the Lambda map."""

    version: Literal[1] = 1
    business: Business
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    intents: list[Intent] = Field(..., min_length=1)
    fallback: Fallback
    twilio: TwilioSettings

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _validate_unique_intent_keys(self) -> IVRConfig:
        keys = [intent.key for intent in self.intents]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"duplicate intent keys: {duplicates}")
        return self

    @property
    def intent_keys(self) -> list[str]:
        """Configured intent keys, excluding the fallback."""
        return [intent.key for intent in self.intents]

    def extension_destinations(self) -> dict[str, dict[str, str]]:
        """Destinations needing DTMF, keyed by intent, for the Lambda ``/dial`` route.

        Studio's Connect Call To widget cannot send digits, so only these
        destinations are routed through Lambda-generated TwiML.
        """
        result: dict[str, dict[str, str]] = {}
        candidates: list[tuple[str, Destination]] = [
            (intent.key, intent.destination) for intent in self.intents
        ]
        candidates.append((FALLBACK_KEY, self.fallback.destination))

        for key, destination in candidates:
            if isinstance(destination, PhoneDestination):
                send_digits = destination.send_digits
                if send_digits:
                    result[key] = {"number": destination.number, "sendDigits": send_digits}
        return result


def config_search_paths() -> list[Path]:
    """Candidate locations for ``ivr-config.json``, most specific first.

    Inside the AgentCore bundle the file sits next to this module. When the
    wizard or the Studio generator import this module from the repo, the file
    sits one level up at the example root.
    """
    paths: list[Path] = []
    override = os.environ.get("IVR_CONFIG_PATH")
    if override:
        paths.append(Path(override))
    module_dir = Path(__file__).resolve().parent
    paths.append(module_dir / CONFIG_FILENAME)
    paths.append(module_dir.parent / CONFIG_FILENAME)
    return paths


def load_config(path: str | Path | None = None) -> IVRConfig:
    """Load and validate the IVR configuration.

    Args:
        path: Explicit path to a config file. When omitted, the locations from
            :func:`config_search_paths` are tried in order.

    Returns:
        The validated configuration.

    Raises:
        FileNotFoundError: If no config file exists at any candidate location.
        pydantic.ValidationError: If the file exists but is invalid.
    """
    candidates = [Path(path)] if path is not None else config_search_paths()
    for candidate in candidates:
        if candidate.is_file():
            return IVRConfig.model_validate_json(candidate.read_text(encoding="utf-8"))

    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        f"No {CONFIG_FILENAME} found. Searched: {searched}. "
        f"Run 'make configure' in deploy/agentcore_aws_lambda to create one."
    )
