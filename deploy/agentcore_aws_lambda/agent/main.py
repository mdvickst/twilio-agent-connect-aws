"""TAC AI IVR agent for AWS Bedrock AgentCore.

Voice is the IVR: the agent triages the caller and calls ``transfer_call``, which
ends the ConversationRelay session with an intent slug for the Studio flow to
route on. SMS shares the business context but has no transfer tool, since there
is no live call to hand off.
"""

from ivr_config import load_config
from prompt import build_sms_system_prompt, build_voice_system_prompt
from strands import Agent
from strands.models import BedrockModel
from strands.session import FileSessionManager
from tac import TAC
from tac.channels.sms import SMSChannelConfig
from tac.channels.voice import VoiceChannelConfig
from tac.models.session import ConversationSession
from tac_config import create_tac_config
from transfer import create_transfer_tool

from tac_aws.connectors import StrandsConnector
from tac_aws.server import TACAgentCoreApp

MODEL_ID = "amazon.nova-pro-v1:0"

# Loaded once at cold start. make build copies ivr-config.json into this
# directory so it ships inside the AgentCore code bundle.
IVR = load_config()

# Initialize TAC with credentials from Secrets Manager
tac = TAC(config=create_tac_config())


def create_agent(context: ConversationSession) -> Agent:
    """
    Agent factory for the Strands connector.

    Called once per conversation to create an isolated agent instance. Uses
    FileSessionManager to persist conversation history across microVM shutdowns.

    The transfer tool closes over ``context`` — the same ConversationSession
    object TAC's voice channel reads when deciding whether to send the
    ConversationRelay ``end`` message.

    See:
    - Strands Session Management: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/
    - AgentCore Managed Session Storage: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html
    """
    is_voice = context.channel == "voice"

    return Agent(
        model=BedrockModel(model_id=MODEL_ID),
        system_prompt=(
            build_voice_system_prompt(IVR) if is_voice else build_sms_system_prompt(IVR)
        ),
        tools=[create_transfer_tool(context, IVR.intent_keys)] if is_voice else [],
        session_manager=FileSessionManager(
            session_id=context.conversation_id, storage_dir="/mnt/workspace/.sessions"
        ),
    )


# Create Strands connector
connector = StrandsConnector(
    tac=tac,
    agent_factory=create_agent,
    voice_config=VoiceChannelConfig(memory_mode="once"),
    sms_config=SMSChannelConfig(memory_mode="always"),
)

# Create app. The greeting is sent agent-side on the ConversationRelay setup
# message, which is why the Studio widget's Welcome Greeting field is left empty.
tac_app = TACAgentCoreApp(
    tac=tac,
    voice_channel=connector.voice,
    sms_channel=connector.sms,
    welcome_message=IVR.business.greeting,
)

# For AgentCore deployment
app = tac_app.app

if __name__ == "__main__":
    tac_app.run()
