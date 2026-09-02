# twilio-agent-connect-aws Deployment Guide

Production deployment options for twilio-agent-connect-aws.

## Deployments

### AWS Lambda + Bedrock AgentCore — AI IVR (Recommended)

**What it deploys:** A production AI IVR. Callers describe what they need in natural language and are transferred to the right destination — no DTMF menu. A Studio flow runs ConversationRelay against a Bedrock AgentCore runtime; the agent triages and transfers. SMS also works through the same Lambda.

**Architecture:** Studio ConversationRelay connects directly to AgentCore via WebSocket. Lambda handles the Studio `/session` route and Conversation Orchestrator SMS webhooks. No Fargate, ALB, or VPC.

**Key features:**

- AI triage: callers speak naturally, agent routes to the right team
- Direct WebSocket connection (best performance)
- Fully serverless (pay-per-request)
- Single CDK command deployment (`make configure` → `make bootstrap` → `make deploy`)

**Guide:** [`agentcore_aws_lambda/README.md`](agentcore_aws_lambda/README.md)

**Best for:** Replacing a DTMF IVR tree with a natural-language AI that routes callers to the right destination

---

**Note on the other three targets below:** `agentcore_aws_fargate`, `strands_aws_fargate`, and `bedrock_aws_fargate` are plain conversational-assistant examples (no IVR, no intent routing). They demonstrate alternative runtime and infrastructure choices but do not include the Studio flow or destination routing logic.

---

### AWS Fargate + Bedrock AgentCore

**Architecture:** TAC Server runs on Fargate behind ALB. Server connects to AgentCore runtime via HTTP/WebSocket.

**Key features:**

- Custom agent code deployment to AgentCore
- TAC Server on ECS Fargate + ALB
- Docker containerized deployment
- CloudFormation templates

**Guide:** [`agentcore_aws_fargate/README.md`](agentcore_aws_fargate/README.md)

**Best for:** Existing Fargate infrastructure or specific VPC requirements

---

### AWS Fargate + Bedrock Agents

**Architecture:** TAC Server runs on Fargate behind ALB. Server invokes console-created Bedrock Agents via API.

**Key features:**

- Console-created agents with action groups and knowledge bases
- Fully managed agent service
- TAC Server on ECS Fargate + ALB
- CloudFormation templates

**Guide:** [`bedrock_aws_fargate/README.md`](bedrock_aws_fargate/README.md)

**Best for:** Using AWS Bedrock Agents created in AWS Console

---

### AWS Fargate + Strands

**Architecture:** TAC Server runs on Fargate behind ALB. Strands agents created per-conversation with direct Bedrock LLM calls.

**Key features:**

- Strands SDK agent framework
- Per-conversation agent instances
- TAC Server on ECS Fargate + ALB
- CloudFormation templates

**Guide:** [`strands_aws_fargate/README.md`](strands_aws_fargate/README.md)

**Best for:** Strands framework with per-conversation state management
