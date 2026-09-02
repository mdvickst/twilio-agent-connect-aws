# TAC AgentCore + Lambda — AI IVR Deployment

Deploy an AI-powered IVR with Twilio Agent Connect, AWS Bedrock AgentCore, and Lambda. Callers describe what they need in natural language and are transferred to the right destination — no DTMF menu required.

## How It Works

```mermaid
graph TD
    Caller([Caller])

    subgraph Twilio["Twilio Cloud"]
        Number[Phone Number]
        Studio["Studio Flow\n'TAC AI IVR — &lt;business&gt;'"]
        CR[ConversationRelay widget\nai_agent]
        Route["split-based-on\nroute_intent\n{{widgets.ai_agent.HandoffData}}"]
        Dest["dial_billing / dial_sales\n/ dial_fallback …"]
    end

    subgraph AWS["AWS Account"]
        Lambda["Lambda Function URL\n/session · /dial · /webhook"]
        AgentCore["Bedrock AgentCore Runtime\nTAC + Strands agent"]
    end

    Caller -->|incomingCall| Number
    Number -->|trigger| Studio
    Studio -->|"get_session\nPOST /session {CallSid, Token}"| Lambda
    Lambda -->|"AgentCore presigned wss:// URL"| Studio
    Studio --> CR
    CR <-->|"ConversationRelay WebSocket\nagent triages, calls transfer_call(intent)\nTAC sends {type:'end', handoffData:'&lt;slug&gt;'}"| AgentCore
    CR -->|"success / failed"| Route
    Route -->|"slug match"| Dest
    Route -->|"no match"| Fallback[dial_fallback]
    Dest -->|"callCompleted"| Check["check_&lt;key&gt;\nsplit on DialCallStatus"]
    Check -->|"not completed"| NoAnswer["say_no_answer"]

    style Caller fill:#e1f5ff
    style Twilio fill:#f0f0f0
    style AWS fill:#fff4e6
    style Lambda fill:#fff9c4
    style AgentCore fill:#f3e5f5
```

A caller dials the Twilio number. The Studio flow calls the Lambda `/session` route to get an AgentCore presigned WebSocket URL, then runs a ConversationRelay widget against it. The agent triages the caller in natural language and calls the `transfer_call` tool with an intent key. TAC sends `{"type":"end","handoffData":"<slug>"}` to ConversationRelay after the closing sentence. The `route_intent` split checks `HandoffData` and branches to the matching destination widget.

**SMS** reaches the agent through a separate path: Conversation Orchestrator delivers the webhook to the Lambda `/webhook` route, bypassing the Studio flow.

---

## What the Deploy Creates

`make deploy` creates or modifies exactly these resources:

- **Three CloudFormation stacks:**
  - `TacSecretsStack` — Secrets Manager secret holding Twilio credentials
  - `TacAgentCoreStack` — Bedrock AgentCore runtime with the TAC + Strands agent
  - `TacLambdaStack` — Lambda function URL (four routes: `/session`, `/dial`, `/twiml`, `/webhook`)
- **One Twilio Studio flow** named `TAC AI IVR — <your business name>`
- **One Twilio phone number webhook change** — the IVR number's voice webhook is pointed at the Studio flow

Nothing else in your Twilio account is created or modified. The Conversation Orchestrator configuration is read but not changed by `make deploy`; capture rules require a separate step (see below).

---

## Prerequisites

### Required Tools

- **[AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)** — Command-line tool for AWS
- **[Node.js 24+](https://nodejs.org/)** — For CDK infrastructure
- **[Python 3.10+](https://www.python.org/downloads/)** — For agent code
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — Python package manager
- **[Docker](https://docs.docker.com/get-docker/)** — For Lambda packaging (must be running)

### AWS Account Requirements

- **Active AWS Account** with access to:
  - **Bedrock** (Amazon Nova Pro or Claude models)
  - **AgentCore**, **Lambda**, **CloudFormation**, and **IAM**
- **Recommended region:** `us-east-1` (or your preferred region with Bedrock access)

### Twilio Requirements

- A Twilio phone number
- A **Conversation Orchestrator configuration** (`WR...`) with **capture rules** for the IVR number — see the next section
- An **API Key** (`SK...`) and its Secret. A **Standard** key is sufficient — a Main key is not required. Create one at **Console → Account → API keys & tokens**.
  - The Secret is displayed **once**, when the key is created. It cannot be retrieved later — if you lose it, create a new key.
  - The wizard's **Test connection** authenticates with the API Key and Secret, **not** the Auth Token. It reads only `IncomingPhoneNumbers` and the Conversation Orchestrator configurations, both scoped to the Account SID you enter — it never touches `/Accounts`, which is account management and would require a Main key.
  - A `20003` there means the key or secret is wrong, or the key has no access to that Account SID.

---

## Hard Prerequisite: Conversation Orchestrator Capture Rules

**This step is required. The IVR will not work without it.**

Twilio's Studio ConversationRelay widget cannot set `conversationConfiguration`. That means Conversation Orchestrator must capture traffic for the IVR phone number *passively*, via capture rules on the configuration. Passive capture is what creates the conversation that TAC looks up by `CallSid`.

Without capture rules, TAC's voice channel polls for a conversation keyed on the `CallSid` for roughly 3.75 seconds, then raises. The WebSocket dies, the ConversationRelay widget takes its `failed` transition, and **every call silently drops to the fallback destination**.

### Add Capture Rules in the Console

1. Open **Twilio Console → Conversation Orchestrator → Configurations**
2. Select the configuration you will use (`conversationConfigurationId` in `.env`)
3. Go to the **Channel Traffic** tab
4. Under **Automatically captured traffic**, add your IVR phone number for both **Voice** and **Messaging**
5. Save

### Or Add Them with Make

After running `make configure`, run:

```bash
make capture-rules
```

This adds the capture rules programmatically. Run `make preflight` afterward to confirm.

### Verify with Make

```bash
make preflight
```

`make preflight` checks that Voice and Messaging capture rules exist for the IVR number and prints an actionable error if they are missing. Use it to verify capture rules without deploying. `make deploy` runs this check automatically as part of `studio-deploy` and stops with an actionable error before creating or modifying anything in Twilio if capture rules are missing — so a misconfigured account cannot end up with a published flow that drops every call.

---

## AWS Setup

### 1. Create IAM User and Access Keys

**Step 1: Create the policy**

1. Sign in to [AWS Console](https://console.aws.amazon.com)
2. Navigate to **IAM** → **Policies**
3. Click **Create policy**
4. Click the **JSON** tab
5. Copy the contents of [`iam-policy.json`](https://github.com/twilio/twilio-agent-connect-aws/blob/main/deploy/agentcore_aws_lambda/iam-policy.json) and paste it
6. Click **Next**
7. Enter a policy name (e.g., `TACDeploymentPolicy`)
8. (Optional) Add a description
9. Click **Create policy**

**Step 2: Create the user**

1. Navigate to **IAM** → **Users**
2. Click **Create user**
3. Enter a **User name** (e.g., `tac-deployment-user`)
4. Click **Next**
5. On "Set permissions" page, select **Attach policies directly**
6. Search for `TACDeploymentPolicy` (the policy you just created)
7. Check the box next to it
8. Click **Next**
9. Review and click **Create user**

**Step 3: Create access key**

1. After user creation, click the **Security credentials** tab
2. Under **Access keys**, click **Create access key**
3. Choose use case: **Command Line Interface (CLI)**
4. Check the confirmation box and click **Next**
5. (Optional) Add a description tag
6. Click **Create access key**
7. **Save credentials** (secret key only shown once):
   - Access key ID (e.g., `AKIAIOSFODNN7EXAMPLE`)
   - Secret access key
8. Click **Done**

**Note:** The IAM policy in [`iam-policy.json`](https://github.com/twilio/twilio-agent-connect-aws/blob/main/deploy/agentcore_aws_lambda/iam-policy.json) follows the principle of least privilege, scoping permissions to only the resources needed for this deployment (CloudFormation stacks, S3 CDK assets, Lambda functions, BedrockAgentCore runtimes). For tighter security in production, replace `*` in account IDs with your specific AWS account ID.

### 2. Configure AWS CLI Profile

```bash
aws configure --profile your-profile-name
```

When prompted, enter:

- **AWS Access Key ID:** Paste the access key from step 1
- **AWS Secret Access Key:** Paste the secret key from step 1
- **Default region name:** `us-east-1` (or your preferred region)
- **Default output format:** `json`

### 3. Verify Configuration

```bash
aws sts get-caller-identity --profile your-profile-name
```

Expected output:
```json
{
    "UserId": "AIDAI...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/your-username"
}
```

Save your **Account ID** (e.g., `123456789012`) — you will need it in `make configure`.

---

## Known Unverified

No call has been placed through this deployment end to end.

The ConversationRelay widget's **type** and **`url` property** are confirmed: the
generated flow validates against `POST /v2/Flows/Validate` on a real account. The
type is `run-conversation-relay` — note the hyphen between "conversation" and
"relay".

What remains unverified is `CR_VOICE_PROPERTY_MAP` in
[`studio/widgets.py`](https://github.com/twilio/twilio-agent-connect-aws/blob/main/deploy/agentcore_aws_lambda/studio/widgets.py)
— the optional voice settings (`language`, `ttsProvider`, `voice`,
`transcriptionProvider`, `speechModel`). **Validation cannot confirm these**: the
Flows validator silently accepts unknown properties, so a wrong name is ignored at
runtime rather than rejected — the setting simply doesn't apply and the caller gets
Twilio's defaults. If you set voice options in the wizard and they appear to have no
effect, build a ConversationRelay widget in the Studio Console with those fields set
and compare property names:

```bash
twilio api:studio:v2:flows:fetch --sid FWxxxxxxxx -o json
```

If you leave the voice settings unset, this does not affect you.

---

## Quick Start

### Step 1 — Configure the IVR

```bash
make configure
```

This launches a local wizard at `http://127.0.0.1:8787`. Walk through the wizard to set your business name, greeting, intents, destinations, voice settings, and Twilio credentials. The wizard writes `ivr-config.json` and `.env` to this directory. Press Ctrl-C when you are done.

**`make configure` must run before `make bootstrap` and `make deploy`** — both commands read `.env`.

### Step 2 — Bootstrap CDK (one-time)

```bash
make bootstrap
```

Installs CDK dependencies and bootstraps your AWS account for CDK deployments. Only needs to be run once per account/region.

### Step 3 — Add Capture Rules

If you have not already done this, add Voice and Messaging capture rules for the IVR number to your Conversation Orchestrator configuration — either in the [Console](#add-capture-rules-in-the-console) or with:

```bash
make capture-rules
```

Then confirm:

```bash
make preflight
```

`make deploy` checks capture rules automatically and stops before touching Twilio if they are missing, but running `make preflight` now surfaces the problem before the multi-stack deploy starts.

See the [Hard Prerequisite](#hard-prerequisite-conversation-orchestrator-capture-rules) section for background.

### Step 4 — Deploy

```bash
make deploy
```

Builds the agent and Lambda code, deploys the three CloudFormation stacks, publishes the Studio flow, and wires the phone number. The first deploy takes around 10–15 minutes; subsequent deploys are faster.

**If the Studio step fails,** the AWS stacks are already deployed — the CloudFormation stacks run first, and the flow is published afterwards. What happened in Twilio depends on where the failure occurred: if the flow *publication* failed, nothing in your Twilio account was created or changed; if the flow published but the number-wiring step failed, the flow exists in Studio but your phone number's webhook was not changed (the deploy output will say so). Either way, fix the reported problem and re-run `make deploy`; the flow is published idempotently by friendly name, so re-running does not create duplicates. Use `make destroy` if you want to remove the AWS resources instead.

After a successful deploy you should see:

```
✓ IVR deployed
```

---

## Destinations Reference

The wizard collects one or more intents, each with a destination, plus a required fallback. The generated Studio flow uses different widgets depending on destination type.

| Destination type | What to provide | Studio widget | Notes |
|---|---|---|---|
| Phone number | E.164 number (e.g. `+15551234567`) | `connect-call-to` (noun: number) | Caller ID is `{{contact.channel.address}}` — the *inbound* caller's number, not the IVR number. The destination sees the original caller's CID with no STIR/SHAKEN attestation on the transferred leg, which some international or SIP destinations may reject. Use `{{flow.channel.address}}` in `studio/flow_builder.py` instead if you want the IVR number presented. |
| Phone + extension | E.164 number + extension digits | `add-twiml-redirect` to Lambda `/dial` | Studio's dial widget has no `sendDigits`, so extensions are handled by Lambda-generated TwiML. `w` characters in the DTMF string represent half-second pauses. |
| SIP URI | `sip:agent@pbx.example.com` | `connect-call-to` (noun: sip) | Custom headers must start with `X-` per Twilio's requirement. Digest credentials (`username` / `password`) are supported. Headers are appended to the URI as URL-encoded parameters. |
| Twilio Client | Client identity string | `connect-call-to` (noun: client) | Up to 121 characters |

The fallback destination follows the same rules. All non-extension destinations get a `check_<key>` split after the dial that reads `DialCallStatus` — the "couldn't connect" apology only plays when the call was genuinely not answered, not after a normal call ends.

---

## Editing After Deploy

**Changing the greeting, voice, or destinations:** Open the Studio flow in the Canvas (`Twilio Console → Studio`), find `TAC AI IVR — <your business>`, and edit the widgets directly. Changes take effect on the next call without redeploying.

**Changing intents (adding, removing, or renaming them):** Re-run the wizard and redeploy, because the agent's system prompt and the flow's `route_intent` split branches must agree. Out-of-sync intent keys cause the agent to return a slug that the split does not recognize, routing every call to the fallback.

```bash
make configure   # update ivr-config.json and .env
make deploy      # rebuild and republish
```

---

## Memory and Transcripts

TAC's Conversation Memory is active. The caller's phone number resolves their profile, so returning-caller context is available to the agent.

**Voice transcripts are not written into Conversation Memory.** Because this deployment uses passive capture rather than `conversationConfiguration`, `VoiceChannel.send_response` writes only to the WebSocket — the caller's utterances in this call are not stored. Memory *retrieval* still works (returning-caller profile is intact), but this call's conversation text will not appear in memory for future calls.

SMS messages are stored normally.

---

## View Logs

CloudWatch log groups are created after the first invocation.

### AgentCore Logs

1. Go to [CloudWatch Console](https://console.aws.amazon.com/cloudwatch/)
2. Click **Logs** → **Log Management** → **Log groups**
3. Search: `/aws/bedrock-agentcore/runtimes/tac_tac_agent-`

### Lambda Logs

1. Go to [CloudWatch Console](https://console.aws.amazon.com/cloudwatch/)
2. Click **Logs** → **Log Management** → **Log groups**
3. Search: `/aws/lambda/TacLambdaStack-`

---

## Manual Verification Checklist

No call has been placed through this deployment in a controlled test. Work through this checklist yourself after deploy to confirm each stage of the flow.

- [ ] Call the number; confirm you hear the configured greeting.
- [ ] Ask for one intent in your own words; confirm the agent names the destination in one sentence, then the call transfers.
- [ ] For an extension destination, confirm the DTMF digits are sent after the pause.
- [ ] Say something unrelated to every intent; confirm you reach the fallback destination.
- [ ] Ask for "a person"; confirm you reach the fallback immediately.
- [ ] In the Studio execution log, confirm `HandoffData` is set to the expected slug.
- [ ] In the AgentCore log group `/aws/bedrock-agentcore/runtimes/tac_tac_agent-`, confirm no errors.
- [ ] Send an SMS to the number; confirm the assistant replies and does not attempt a transfer.

---

## Update Code

After editing agent or Lambda code:

```bash
make deploy
```

---

## Destroy

To delete all AWS resources and remove the Studio flow:

```bash
make destroy
```

---

## Troubleshooting

### Every call goes straight to the fallback destination

Look for `Expected exactly 1 conversation for call_sid` in the AgentCore logs (`/aws/bedrock-agentcore/runtimes/tac_tac_agent-`).

**Cause:** The Conversation Orchestrator capture rule is missing or was not in place when the call arrived. Without it, TAC's voice channel polls for a conversation keyed on the `CallSid`, times out after ~3.75 seconds, and the WebSocket dies. ConversationRelay takes its `failed` transition, which goes to the fallback.

**Fix:** Run `make capture-rules` then `make preflight` to confirm. Wait a minute after adding rules before testing again, as changes may take time to propagate.

### `get_session` fails in the Studio execution log

`IVR_SESSION_TOKEN` in `.env` no longer matches the token embedded in the published Studio flow.

**Fix:** Re-run `make deploy`. Deploy re-publishes the flow with the token from `.env`.

### Studio rejects the flow on deploy (400 from the Flows API)

The ConversationRelay widget's type string or property names changed.

**Background:** `CR_WIDGET_TYPE`, `CR_URL_PROPERTY`, and `CR_VOICE_PROPERTY_MAP` in [`studio/widgets.py`](https://github.com/twilio/twilio-agent-connect-aws/blob/main/deploy/agentcore_aws_lambda/studio/widgets.py) are **unverified guesses**. The ConversationRelay widget shipped in March 2026 and is absent from Twilio's published widget JSON schemas. The values have not been confirmed against a real account. If they are wrong, the Flows API returns a 400.

**Fix:** Run the discovery probe to find the correct type string (from the repo root, with API key credentials — `studio/discover.py` requires `TWILIO_API_KEY` and `TWILIO_API_SECRET`; an auth token alone exits with an error):

```bash
TWILIO_ACCOUNT_SID=ACxxx TWILIO_API_KEY=SKxxx TWILIO_API_SECRET=xxx \
    PYTHONPATH=deploy/agentcore_aws_lambda \
    uv run python -m studio.discover
```

Then open a Studio flow in the Console, add a ConversationRelay widget, and fetch the flow definition via the Flows API to confirm the property names. Update `studio/widgets.py` with the correct values.

### The agent transfers to the wrong destination

Intent descriptions overlap. The agent routes on the descriptions you provided in `make configure`, so overlapping descriptions produce ambiguous routing.

**Fix:** Make intent descriptions mutually exclusive. For example, do not have both "billing questions or payment issues" and "account questions" — a caller asking about their bill matches both. Re-run `make configure` and `make deploy` after updating.

### CDK bootstrap fails with S3 public access block errors

**Symptom:** `make bootstrap` fails with an error about S3 public access block configuration, such as:
```
Error: Failed to create S3 bucket: The S3 bucket that was created for the CDK bootstrap cannot be created with public access block enabled
```

**Cause:** Some AWS accounts or organizations have strict S3 security policies that conflict with CDK's default bootstrap configuration.

**Solution:**

**Security Warning:** Only use this workaround if absolutely necessary. Disabling public access block configuration weakens the security posture of your CDK bootstrap resources.

If you encounter this error and have confirmed with your AWS administrator that it is acceptable, you can manually run bootstrap with the flag:

```bash
cd cdk && AWS_PROFILE=your-profile-name npx cdk bootstrap \
    --public-access-block-configuration false \
    aws://123456789012/us-east-1
```

**Better alternatives:**

1. Work with your AWS administrator to adjust organization-level S3 policies
2. Use a CDK bootstrap configuration that aligns with your organization's security requirements
3. Consider using a separate AWS account without organization-level restrictions for development

### Node.js not found or npm commands fail

**Symptom:** `npm: command not found` or `node: command not found` after installing Node.js via Homebrew.

**Cause:** Homebrew installs some Node.js versions as "keg-only" (not automatically linked to PATH).

**Solution:**

Check your Node.js installation:
```bash
brew list | grep node
```

If you see `node@24`, add it to your PATH:
```bash
# For zsh (default macOS shell)
echo 'export PATH="/opt/homebrew/opt/node@24/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# For bash
echo 'export PATH="/opt/homebrew/opt/node@24/bin:$PATH"' >> ~/.bash_profile
source ~/.bash_profile
```

Verify:
```bash
node --version  # Should show v24.x.x
npm --version   # Should show 10.x.x
```

**Note:** This project requires Node.js 24+ as specified in `cdk/package.json`. Make sure you install the correct version.
