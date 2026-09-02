"""Local FastAPI app backing the IVR configuration page.

Bound to 127.0.0.1 by ``make configure``. Holds no session state: the browser
sends credentials with each request that needs them, and nothing is cached.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ivr_config import CONFIG_FILENAME, IVRConfig
from pydantic import BaseModel, Field, ValidationError

from .twilio_lookup import (
    AccountMismatchError,
    TwilioCredentials,
    list_conversation_configurations,
    list_phone_numbers,
    verify,
)
from .writer import (
    ENV_FILENAME,
    SECRET_ENV_KEYS,
    existing_env_values,
    generate_session_token,
    redact,
    write_config,
    write_env,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

NEXT_COMMAND = "cd deploy/agentcore_aws_lambda && make deploy"


class AwsSettings(BaseModel):
    """AWS deployment target, written to .env for the Makefile and CDK."""

    profile: str = Field(..., min_length=1)
    account_id: str = Field(..., alias="accountId", pattern=r"^\d{12}$")
    region: str = Field(..., alias="region", min_length=1)

    model_config = {"populate_by_name": True}


class SaveRequest(BaseModel):
    """Everything the page submits when the user clicks Save."""

    credentials: TwilioCredentials
    aws: AwsSettings
    config: dict[str, Any]


def _env_updates(request: SaveRequest, config: IVRConfig, session_token: str) -> dict[str, str]:
    return {
        "AWS_PROFILE": request.aws.profile,
        "AWS_ACCOUNT_ID": request.aws.account_id,
        "AWS_REGION": request.aws.region,
        "TWILIO_ACCOUNT_SID": request.credentials.account_sid,
        "TWILIO_AUTH_TOKEN": request.credentials.auth_token,
        "TWILIO_API_KEY": request.credentials.api_key,
        "TWILIO_API_SECRET": request.credentials.api_secret,
        "TWILIO_PHONE_NUMBER": config.twilio.phone_number,
        "TWILIO_CONVERSATION_CONFIGURATION_ID": config.twilio.conversation_configuration_id,
        "IVR_SESSION_TOKEN": session_token,
    }


def create_app(example_root: Path) -> FastAPI:
    """Build the wizard app rooted at ``example_root``.

    Args:
        example_root: Directory holding ``.env`` and ``ivr-config.json`` — normally
            ``deploy/agentcore_aws_lambda``. Parameterized so tests use tmp_path.
    """
    app = FastAPI(title="TAC AI IVR configuration", docs_url=None, redoc_url=None)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        """Return the saved config plus non-secret .env values, for re-editing."""
        config_path = example_root / CONFIG_FILENAME
        env_path = example_root / ENV_FILENAME

        config: dict[str, Any] | None = None
        if config_path.is_file():
            try:
                config = IVRConfig.model_validate_json(
                    config_path.read_text(encoding="utf-8")
                ).model_dump(by_alias=True, exclude_none=True)
            except ValidationError:
                config = None

        env_values: dict[str, str] = {}
        if env_path.is_file():
            env_values = existing_env_values(env_path.read_text(encoding="utf-8"))

        return {"config": config, "env": redact(env_values, SECRET_ENV_KEYS)}

    @app.post("/api/resources")
    def resources(credentials: TwilioCredentials) -> dict[str, Any]:
        """Verify credentials and list the numbers and configurations to choose from."""
        try:
            account_name = verify(credentials)
            numbers = list_phone_numbers(credentials)
            configurations = list_conversation_configurations(credentials)
        except Exception as error:
            logger.warning(f"Twilio lookup failed: {type(error).__name__}: {error}")
            raise HTTPException(status_code=400, detail=explain_twilio_failure(error)) from error

        return {
            "accountName": account_name,
            "phoneNumbers": numbers,
            "conversationConfigurations": configurations,
        }

    @app.post("/api/config")
    def save_config(request: SaveRequest) -> dict[str, Any]:
        """Validate and write ivr-config.json and .env."""
        try:
            config = IVRConfig.model_validate(request.config)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=json.loads(error.json())) from error

        env_path = example_root / ENV_FILENAME
        current = (
            existing_env_values(env_path.read_text(encoding="utf-8")) if env_path.is_file() else {}
        )
        session_token = current.get("IVR_SESSION_TOKEN") or generate_session_token()

        config_path = write_config(config, example_root)
        written_env = write_env(_env_updates(request, config, session_token), example_root)

        return {
            "written": [str(config_path), str(written_env)],
            "nextCommand": NEXT_COMMAND,
        }

    return app


def explain_twilio_failure(error: Exception) -> str:
    """Turn a Twilio or transport failure into something the user can act on.

    The raw ``TwilioRestException`` string reports the HTTP path and a docs link
    but never says which field is wrong, which is useless in a form where four
    credentials were entered. Twilio's own error code is the reliable signal, so
    map the ones this endpoint can actually provoke.
    """
    code = getattr(error, "code", None)

    if isinstance(error, AccountMismatchError):
        return str(error)

    if code == 20003:
        return (
            "Twilio rejected the credentials (error 20003). This request is "
            "authenticated with the API Key SID and API Key Secret — not the Auth "
            "Token — so check those two first. Common causes: the secret is wrong "
            "(it is shown only once when the key is created, so it cannot be "
            "recovered — create a new key instead), the API key belongs to a "
            "different account than the Account SID entered, or the Auth Token was "
            "pasted into the API Secret field. A Standard key is sufficient here."
        )
    if code == 20404:
        return (
            "Twilio could not find that Account SID (error 20404). Check it is the "
            "account the API key belongs to — a subaccount SID with a parent-account "
            "key, or vice versa, produces this."
        )
    if code == 20429 or getattr(error, "status", None) == 429:
        return "Twilio rate-limited this request (429). Wait a moment and try again."

    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status in (401, 403):
            return (
                f"Conversation Orchestrator rejected the API key ({status}). The "
                "phone-number lookup may have succeeded — this step calls the "
                "Conversations Control Plane, which needs the same API key to have "
                "access to Conversation Orchestrator on this account."
            )
        return f"Conversation Orchestrator returned HTTP {status}."
    if isinstance(error, httpx.RequestError):
        return f"Could not reach Twilio: {error.__class__.__name__}. Check your network."

    detail = getattr(error, "msg", None) or str(error)
    suffix = f" (Twilio error {code})" if code else ""
    return f"Twilio lookup failed: {detail}{suffix}"


#: Directory holding ``.env`` and ``ivr-config.json`` — the example root, two
#: levels up from this module (``wizard/server.py`` -> ``agentcore_aws_lambda/``).
EXAMPLE_ROOT = Path(__file__).resolve().parent.parent


def default_app() -> FastAPI:
    """Zero-argument factory for ``uvicorn wizard.server:default_app --factory``.

    ``create_app`` takes ``example_root`` so tests can point it at a tmp
    directory, which means uvicorn cannot call it directly. ``make configure``
    uses this wrapper instead.
    """
    return create_app(EXAMPLE_ROOT)
