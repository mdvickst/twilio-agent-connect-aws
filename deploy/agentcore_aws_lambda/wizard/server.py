"""Local FastAPI app backing the IVR configuration page.

Bound to 127.0.0.1 by ``make configure``. Holds no session state: the browser
sends credentials with each request that needs them, and nothing is cached.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ivr_config import CONFIG_FILENAME, IVRConfig
from pydantic import BaseModel, Field, ValidationError

from .twilio_lookup import (
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
            raise HTTPException(status_code=400, detail=str(error)) from error

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
