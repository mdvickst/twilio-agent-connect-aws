"""Write the wizard's output: ivr-config.json and .env."""

from __future__ import annotations

import secrets
from pathlib import Path

from ivr_config import CONFIG_FILENAME, IVRConfig

ENV_FILENAME = ".env"

REDACTED = "•••• set"

#: Keys never echoed back to the browser.
SECRET_ENV_KEYS = {
    "TWILIO_AUTH_TOKEN",
    "TWILIO_API_SECRET",
    "IVR_SESSION_TOKEN",
}


def generate_session_token() -> str:
    """A fresh shared secret for the Lambda ``/session`` route."""
    return secrets.token_urlsafe(32)


def existing_env_values(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` pairs from a .env file, ignoring comments and junk."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def merge_env(existing: str, updates: dict[str, str]) -> str:
    """Apply ``updates`` to a .env file's text, preserving everything else.

    Keys already present are rewritten in place so ordering and surrounding
    comments survive. Keys not present are appended.

    If a key being updated appears more than once in the existing file (e.g.
    after a hand-edit), later duplicate occurrences are dropped so exactly one
    line for that key survives.  Without this, Make's ``-include .env`` and
    ``dotenv.config()`` pick *different* occurrences (last vs. first), causing
    the Studio flow to embed one token and the Lambda to read another — every
    call gets a 403 with no visible error.
    """
    remaining = dict(updates)
    written_keys: set[str] = set()
    lines = existing.splitlines()
    merged: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                merged.append(f"{key}={remaining.pop(key)}")
                written_keys.add(key)
                continue
            if key in written_keys:
                # Later duplicate of a key we already rewrote — drop it so
                # exactly one authoritative line survives.
                continue
        merged.append(line)

    for key, value in remaining.items():
        merged.append(f"{key}={value}")

    return "\n".join(merged).rstrip("\n") + "\n"


def redact(values: dict[str, str], secret_keys: set[str]) -> dict[str, str]:
    """Replace set secrets with a placeholder and drop unset ones entirely."""
    result: dict[str, str] = {}
    for key, value in values.items():
        if key in secret_keys:
            if value:
                result[key] = REDACTED
            continue
        result[key] = value
    return result


def write_config(config: IVRConfig, example_root: Path) -> Path:
    """Write ``ivr-config.json`` using JSON aliases, and return its path."""
    target = example_root / CONFIG_FILENAME
    target.write_text(
        config.model_dump_json(by_alias=True, indent=2, exclude_none=True) + "\n",
        encoding="utf-8",
    )
    return target


def write_env(updates: dict[str, str], example_root: Path) -> Path:
    """Merge ``updates`` into the example's .env, creating it if needed."""
    target = example_root / ENV_FILENAME
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    target.write_text(merge_env(existing, updates), encoding="utf-8")
    return target
