"""Tests for the wizard's file writer."""

from __future__ import annotations

from pathlib import Path

from ivr_config import IVRConfig
from wizard.writer import (
    existing_env_values,
    generate_session_token,
    merge_env,
    redact,
    write_config,
    write_env,
)

from tests.ivr.test_ivr_config import minimal_config_dict


def test_merge_env_collapses_duplicate_key_to_single_updated_line():
    """A hand-edited .env with the same key twice must produce exactly one line.

    Without this fix, Make's ``-include .env`` takes the *last* occurrence and
    ``dotenv.config()`` takes the *first*, so the Studio flow embeds one token
    and the Lambda sees another — every call silently returns 403.
    """
    existing = (
        "AWS_REGION=us-east-1\n"
        "IVR_SESSION_TOKEN=old-token\n"
        "# a comment\n"
        "IVR_SESSION_TOKEN=old-token-duplicate\n"
        "AWS_ACCOUNT_ID=123456789012\n"
    )
    merged = merge_env(existing, {"IVR_SESSION_TOKEN": "new-token"})
    assert merged.count("IVR_SESSION_TOKEN=") == 1
    assert "IVR_SESSION_TOKEN=new-token" in merged
    # Unrelated keys and the comment survive
    assert "AWS_REGION=us-east-1" in merged
    assert "AWS_ACCOUNT_ID=123456789012" in merged
    assert "# a comment" in merged


def test_merge_env_updates_an_existing_key_in_place():
    existing = "AWS_REGION=us-east-1\nTWILIO_PHONE_NUMBER=+1555\n"
    merged = merge_env(existing, {"AWS_REGION": "eu-west-1"})
    assert "AWS_REGION=eu-west-1" in merged
    assert "TWILIO_PHONE_NUMBER=+1555" in merged
    assert merged.count("AWS_REGION=") == 1


def test_merge_env_appends_a_missing_key():
    merged = merge_env("AWS_REGION=us-east-1\n", {"IVR_SESSION_TOKEN": "abc"})
    assert "IVR_SESSION_TOKEN=abc" in merged
    assert "AWS_REGION=us-east-1" in merged


def test_merge_env_preserves_comments_and_blank_lines():
    existing = "# AWS Configuration\n\nAWS_REGION=us-east-1\n"
    merged = merge_env(existing, {"AWS_REGION": "eu-west-1"})
    assert "# AWS Configuration" in merged
    assert "\n\n" in merged


def test_merge_env_handles_values_containing_equals_signs():
    merged = merge_env("", {"TWILIO_API_SECRET": "a=b=c"})
    assert "TWILIO_API_SECRET=a=b=c" in merged


def test_merge_env_ends_with_a_newline():
    assert merge_env("", {"A": "1"}).endswith("\n")


def test_existing_env_values_ignores_comments_and_blanks():
    text = "# comment\n\nAWS_REGION=us-east-1\nBROKEN\nTOKEN=xyz\n"
    assert existing_env_values(text) == {"AWS_REGION": "us-east-1", "TOKEN": "xyz"}


def test_existing_env_values_strips_surrounding_whitespace():
    assert existing_env_values("  AWS_REGION = us-east-1 \n") == {"AWS_REGION": "us-east-1"}


def test_generated_session_tokens_are_long_and_unique():
    first, second = generate_session_token(), generate_session_token()
    assert first != second
    assert len(first) >= 32


def test_redact_replaces_set_secrets_and_leaves_others_alone():
    values = {"TWILIO_AUTH_TOKEN": "supersecret", "AWS_REGION": "us-east-1"}
    redacted = redact(values, {"TWILIO_AUTH_TOKEN"})
    assert redacted["TWILIO_AUTH_TOKEN"] == "•••• set"
    assert redacted["AWS_REGION"] == "us-east-1"


def test_redact_omits_secrets_that_are_not_set():
    assert redact({"TWILIO_AUTH_TOKEN": ""}, {"TWILIO_AUTH_TOKEN"}) == {}


def test_write_config_writes_json_the_loader_can_read(tmp_path: Path):
    config = IVRConfig.model_validate(minimal_config_dict())
    written = write_config(config, tmp_path)

    assert written == tmp_path / "ivr-config.json"
    from ivr_config import load_config

    assert load_config(written).business.name == "Owl Insurance"


def test_write_config_uses_json_aliases_not_python_field_names(tmp_path: Path):
    config = IVRConfig.model_validate(minimal_config_dict())
    text = write_config(config, tmp_path).read_text()
    assert "phoneNumber" in text
    assert "phone_number" not in text


def test_write_env_creates_the_file_when_absent(tmp_path: Path):
    written = write_env({"AWS_REGION": "us-east-1"}, tmp_path)
    assert written == tmp_path / ".env"
    assert "AWS_REGION=us-east-1" in written.read_text()


def test_write_env_merges_into_an_existing_file(tmp_path: Path):
    (tmp_path / ".env").write_text("# header\nAWS_REGION=us-east-1\n")
    write_env({"AWS_PROFILE": "dev"}, tmp_path)

    text = (tmp_path / ".env").read_text()
    assert "# header" in text
    assert "AWS_REGION=us-east-1" in text
    assert "AWS_PROFILE=dev" in text
