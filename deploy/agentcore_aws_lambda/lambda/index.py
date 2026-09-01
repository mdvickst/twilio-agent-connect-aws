"""Lambda Function - Twilio Webhook Proxy with TAC Integration.

Endpoints:
- /session: Studio HTTP Request widget fetches the AgentCore presigned wss URL
- /dial:    TwiML for destinations needing an extension (DTMF)
- /twiml:   Voice calls (unused when the Studio flow owns the call)
- /webhook: Conversation Orchestrator webhooks (SMS)

/session and /dial are dispatched here, before AgentCoreLambdaProxy, because the
proxy validates a Twilio signature on every path and Studio's HTTP Request widget
cannot send one.
"""

import json
import os
from typing import Any

from bedrock_agentcore.runtime import AgentCoreRuntimeClient
from credentials import fetch_twilio_auth_token
from routes import DIAL_PATH, SESSION_PATH, handle_dial, handle_session

from tac_aws.proxy import AgentCoreLambdaProxy, TwilioSignatureValidator

# Environment variables
AGENTCORE_RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
TWILIO_SECRET_ARN = os.environ["TWILIO_SECRET_ARN"]
TWILIO_CONVERSATION_CONFIGURATION_ID = os.environ["TWILIO_CONVERSATION_CONFIGURATION_ID"]
AWS_REGION = os.environ["AWS_REGION"]

# IVR wiring. IVR_SESSION_TOKEN authenticates the Studio HTTP Request widget;
# IVR_EXTENSION_DESTINATIONS is the intent -> {number, sendDigits} map that CDK
# derives from ivr-config.json.
IVR_SESSION_TOKEN = os.environ.get("IVR_SESSION_TOKEN", "")
IVR_EXTENSION_DESTINATIONS: dict[str, dict[str, str]] = json.loads(
    os.environ.get("IVR_EXTENSION_DESTINATIONS", "{}")
)

# Fetch Twilio auth token from Secrets Manager
twilio_auth_token = fetch_twilio_auth_token(TWILIO_SECRET_ARN)

proxy = AgentCoreLambdaProxy(
    agentcore_runtime_arn=AGENTCORE_RUNTIME_ARN,
    conversation_configuration_id=TWILIO_CONVERSATION_CONFIGURATION_ID,
    twilio_auth_token=twilio_auth_token,
)

signature_validator = TwilioSignatureValidator(twilio_auth_token)
runtime_client = AgentCoreRuntimeClient(region=AWS_REGION)


def presign_websocket_url(call_sid: str) -> str:
    """Presign the AgentCore WebSocket URL, using CallSid as the session ID."""
    return str(
        runtime_client.generate_presigned_url(
            runtime_arn=AGENTCORE_RUNTIME_ARN, session_id=call_sid, expires=300
        )
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route IVR paths here, everything else to the TAC proxy."""
    request_path = event.get("rawPath", "/")

    if request_path.startswith(SESSION_PATH):
        return handle_session(
            event, expected_token=IVR_SESSION_TOKEN, presign=presign_websocket_url
        )

    if request_path.startswith(DIAL_PATH):
        return handle_dial(
            event,
            destinations=IVR_EXTENSION_DESTINATIONS,
            validator=signature_validator,
        )

    return proxy.lambda_handler(event, context)
