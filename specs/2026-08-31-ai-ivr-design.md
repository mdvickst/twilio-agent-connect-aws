# AI-Powered IVR — Design

**Date:** 2026-08-31
**Status:** Approved design, pending implementation plan
**Scope:** Rewrite `deploy/agentcore_aws_lambda` from a generic assistant into a deployable AI IVR.

> Spec location note: this lives in `specs/` rather than `docs/`, because `docs/` is the
> published MkDocs site (`mkdocs.yml` has an explicit `nav`) and an internal design doc
> placed there would be built and published alongside the API reference.

## Goal

Let a Twilio customer replace a DTMF phone tree with a ConversationRelay AI agent that
triages the caller's request in natural language and transfers them to the destination the
old tree would have reached. Configuration happens on a local web page: a business
description, two or more intents, and a destination per intent. The output is an AWS
AgentCore deployment plus a published Studio flow with ConversationRelay and the
handoffs wired up.

Replaces the behavior of `deploy/agentcore_aws_lambda` in place. The generic-assistant
example remains available in the three other deploy targets (`agentcore_aws_fargate`,
`strands_aws_fargate`, `bedrock_aws_fargate`).

Note that the Twilio Code Exchange sample this is modeled on
([ai-phone-agent-conversation-relay](https://www.twilio.com/code-exchange/ai-phone-agent-conversation-relay))
has no web UI and no transfer logic — it configures via `.env` only. The wizard page and
the intent/destination model are net-new work, not a port.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Wizard model | Local page via `make configure`, then `make deploy` | No hosting, works before AWS creds exist, config file is reviewable |
| Call flow | ConversationRelay widget inside the Studio flow | Whole IVR visible and editable in the Studio canvas without redeploying AWS |
| Destinations | Native `connect-call-to` widgets; Lambda `/dial` only for extensions | Studio's widget has no `sendDigits`; keep everything else canvas-editable |
| Channels | Voice is the IVR; SMS stays a plain assistant | No regression to the existing example; transferring a text to a SIP URI is meaningless |
| No-match | Required fallback destination | No caller reaches a dead end |
| Provisioning | Discover and wire; the Studio flow is the only Twilio resource created, and capture rules are added only via an explicit opt-in target | Removes copy-paste friction at low blast radius |
| Orchestrator | Conversation Orchestrator passive capture rules on both channels | Studio's CR widget cannot set `conversationConfiguration` |

## Architecture

```
Caller ──dials──► Twilio Number ──voice webhook──► Studio Flow "TAC AI IVR"

  trigger(incomingCall)
      ▼
  get_session   [make-http-request]  POST {LambdaUrl}/session
                 body {"CallSid":"{{trigger.call.CallSid}}","Token":"<token>"}
                 200 → {"websocket_url":"wss://…bedrock-agentcore…?X-Amz-…"}
      ├─ fail ─────────────────────────────────────► dial_fallback
      ▼
  ai_agent      [conversationrelay]
                 url = {{widgets.get_session.parsed.websocket_url}}
                 welcomeGreeting = ""   ← the agent sends it, see below
                 language / ttsProvider / voice / speechModel from ivr-config
      ├─ failed ───────────────────────────────────► dial_fallback
      ▼
  route_intent  [split-based-on]  input {{widgets.ai_agent.HandoffData}}
      ├─ "billing"  ──► dial_billing
      ├─ "sales"    ──► dial_sales
      ├─ "fallback" ──► dial_fallback   (agent asked for it explicitly)
      └─ no match   ──► dial_fallback   (empty, unknown slug, or CR failure)
```

The generator emits an explicit `fallback` match branch *and* a default branch, both pointing
at `dial_fallback`. The agent can name `fallback` deliberately when the caller asks for a
person, and an empty or unrecognized slug lands in the same place.

The AI leg is the existing AgentCore runtime, unchanged apart from the prompt and one tool:

```
Studio ⇄ ConversationRelay ⇄ AgentCore Runtime (presigned wss, session = CallSid)
                               └─ TAC VoiceChannel → StrandsConnector → Strands Agent
                                    system prompt = base + business prompt + intent catalog
                                    tools = [transfer_call(intent)]
                                    transfer_call → session.pending_handoff_data
                                    → TAC sends {"type":"end","handoffData":"billing"}
                                      after the agent's closing sentence
```

`welcomeGreeting` is left empty on the widget on purpose. `TACAgentCoreWebSocketAdapter`
already sends a greeting agent-side on the `setup` message, and its docstring notes this is
required for ConversationRelay to activate speech detection. Setting both would greet twice.
The greeting text comes from the config via `TACAgentCoreApp(welcome_message=...)`.

### Verified TAC behavior

These were read out of the installed `tac` package rather than assumed:

- `channels/voice/channel.py:610-620` sends the WebSocket `end` message only *after* the
  final response token. The caller hears "Sure, connecting you to Billing" and *then* gets
  transferred.
- `models/handoff.py` types `PendingHandoffData.handoff_data` as `str`, forwarded verbatim
  to ConversationRelay.
- `channels/voice/channel.py:674` passes `trigger_message_ready` the same
  `ConversationSession` object that the handoff check reads at line 613. A tool closing over
  the session handed to `agent_factory(context)` therefore mutates the right instance.
- `tools/handoff.py:256` documents setting `session.pending_handoff_data` directly as the
  supported path for custom handoffs, so no `studio_handoff_flow_sid` is required.

### `handoffData` is a bare slug

The agent sends `billing`, not `{"intent":"billing"}`. Studio's `split-based-on` compares a
Liquid value with equality; parsing a JSON string in Liquid is not something to put in the
load-bearing path of a call transfer. `handoff_data` is a free-form `str`, so a slug is legal.

### Conversation Orchestrator via passive capture

Twilio's [Studio CR widget docs](https://www.twilio.com/docs/studio/widget-library/run-conversationrelay)
list URL, welcome greeting, custom parameters, language, TTS provider, voice, speech model,
transcription provider, and AI hints — there is no `conversationConfiguration`, and the widget
is absent from the [published widget JSON schemas](https://www.twilio.com/docs/studio/rest-api/v2/schemas)
entirely. So the conversation is created by **Orchestrator capture rules** on the IVR number
for both `VOICE` and `SMS`, and TAC's existing lookup finds it.

Two consequences, accepted:

1. **Voice transcripts are not written to the conversation.** `VoiceChannel.send_response`
   (`channel.py:530-556`) only writes to the WebSocket; the turn-by-turn communications were
   recorded by ConversationRelay *because* `conversationConfiguration` was set. Passive
   capture records the call, not the utterances. Memory *retrieval* is unaffected — the
   profile resolves from the caller's number — so returning-caller context still works.
2. **A ~3.75 s window.** `_initialize_conversation` polls
   `list_conversations(channel_id=<CallSid>, status=["ACTIVE"])` five times with
   0.25/0.5/1.0/2.0 s backoff (`_POLL_ATTEMPTS = 5`, `_POLL_BASE_DELAY = 0.25`) and then
   raises. There is real headroom because polling only begins on the caller's first *prompt*,
   after ringing, the greeting, and the caller speaking. If it still misses, the WebSocket
   dies, the CR widget takes `failed`, and the caller lands on the operator — safe, but the
   AI never engages.

Because the voice path now depends entirely on a capture rule existing, `make deploy` runs a
**preflight** that reads it rather than discovering the problem on the first live call:
`get_configuration(config_id).channel_settings["VOICE"].capture_rules` returns
`CaptureRule(from_address, to_address, metadata)` objects, so the check asserts a rule whose
`to` matches the IVR number or `*`, for both `VOICE` and `SMS`. It fails with the exact
Console steps to fix. Adding the rules is opt-in via `make capture-rules`, consistent with
the decision not to mutate Twilio resources implicitly. The preflight tolerates key casing
variation in `channel_settings`.

## Config model

One file, `deploy/agentcore_aws_lambda/ivr-config.json` (gitignored), is the single source of
truth. It is consumed by the agent bundle, the Studio flow generator, and the Lambda.

```json
{
  "version": 1,
  "business": {
    "name": "Owl Insurance",
    "prompt": "Owl Insurance sells home and auto policies in 12 US states…",
    "greeting": "Thanks for calling Owl Insurance. How can I help you today?"
  },
  "voice": {
    "language": "en-US",
    "ttsProvider": "ElevenLabs",
    "voice": "…",
    "transcriptionProvider": "Deepgram",
    "speechModel": "nova-3-general"
  },
  "intents": [
    {
      "key": "billing",
      "name": "Billing",
      "description": "Invoices, payments, refunds, account balance.",
      "destination": {
        "type": "phone",
        "number": "+15551230001",
        "extension": "402",
        "extensionPauseSeconds": 2
      }
    },
    {
      "key": "sales",
      "name": "New business",
      "description": "Caller wants a quote or a new policy.",
      "destination": {
        "type": "sip",
        "uri": "sip:sales@pbx.example.com",
        "headers": { "X-Dept": "sales" }
      }
    }
  ],
  "fallback": {
    "name": "Operator",
    "description": "Anything unmatched, or the caller asks for a person.",
    "destination": { "type": "phone", "number": "+15551230000" }
  },
  "twilio": {
    "phoneNumber": "+15550000000",
    "phoneNumberSid": "PN…",
    "conversationConfigurationId": "WR…"
  }
}
```

### Destination types

| Type | Fields | Rendered as |
| --- | --- | --- |
| `phone` | `number`, optional `extension`, `extensionPauseSeconds` (default 2) | No extension → `connect-call-to` with `noun: "number"`. With extension → `add-twiml-redirect` to `/dial?intent=<key>`, returning `<Dial><Number sendDigits="wwww402">`. Each `w` is a 0.5 s pause, so `extensionPauseSeconds` × 2 `w` characters. |
| `sip` | `uri`, optional `headers`, optional `username` / `password` | `connect-call-to` with `noun: "sip"`, `to` = uri plus URL-encoded `?X-Dept=sales&…`. Twilio requires custom SIP headers to be `X-`-prefixed. `username`/`password` populate the widget's fields for non-Twilio SIP. |
| `client` | `identity` | `connect-call-to` with `noun: "client"` |

### Validation

One Pydantic model set validates for both the wizard and the generator:

- At least one intent; the wizard starts with two rows.
- `key` auto-slugged from `name`, editable, unique across intents, and never `fallback`.
- `number` matches E.164; `uri` matches `^sips?:`; SIP header keys match
  `^X-[A-Za-z0-9-]+$`; extension digits match `^[0-9*#]{1,20}$`.
- Fallback destination required.
- Length caps: business prompt 4000 chars, intent description 200 chars, to keep the
  assembled system prompt within model limits.

## Components

### Wizard page — `deploy/agentcore_aws_lambda/wizard/`

FastAPI plus vanilla HTML/CSS/JS, no build step, bound to `127.0.0.1`. Started by
`make configure`.

```
wizard/server.py          routes + static mount
wizard/models.py          Pydantic config models (the shared validator)
wizard/twilio_lookup.py   /api/twilio/numbers, /api/twilio/conversation-configurations
wizard/writer.py          writes ivr-config.json, merges values into .env
wizard/static/index.html
wizard/static/app.js
wizard/static/styles.css
```

Sections, in order:

1. **Credentials** — AWS profile / account / region; Twilio Account SID, Auth Token, API Key,
   API Secret. A "Test connection" button validates and populates section 2.
2. **Number and Conversation Configuration** — dropdowns populated from the account.
3. **Business** — name, business prompt (textarea), greeting, voice and language selects.
4. **Intents** — repeatable rows starting at two, with an `+ Add intent` button and a
   per-row destination editor that switches fields by destination type.
5. **Fallback destination** — the same destination editor; required and not removable.
6. **Save** — validates, writes the files, and prints the next command.

On start the server loads any existing `ivr-config.json` and `.env`, so the page re-edits an
existing IVR rather than only bootstrapping one. Secret fields are write-only: rendered as
`•••• set`, never echoed back into the HTML.

### Agent — `deploy/agentcore_aws_lambda/agent/`

```
agent/ivr_config.py   loads the bundled ivr-config.json (copied in by make build)
agent/prompt.py       build_system_prompt(config) = base rules + business prompt + intent catalog
agent/transfer.py     make_transfer_tool(session, config) → Strands @tool transfer_call(intent)
agent/main.py         voice agent gets the tool, SMS agent does not
```

`transfer_call` constrains `intent` to the configured keys plus `fallback`, sets
`session.pending_handoff_data = PendingHandoffData(handoff_data=<key>)`, and returns a status
dict. The base prompt keeps today's voice rules (one or two sentences, no markdown) and adds:
confirm the destination in one sentence before transferring, never invent a department, and
use `fallback` when unsure.

The agent factory branches on `context.channel` so the SMS agent gets the same business
prompt and knowledge but no transfer tool.

### Studio flow generator — `deploy/agentcore_aws_lambda/studio/`

```
studio/flow_builder.py   build_flow_definition(config, lambda_url, token) → dict   (pure, no network)
studio/provision.py      idempotent create-or-update by friendly_name, publish, wire the number
studio/preflight.py      capture-rule verification described above
```

`provision.py` finds the flow by friendly name (`TAC AI IVR — <business name>`), creates or
updates it with `status="published"`, points the number's `voice_url` at the flow webhook, and
prints the flow SID and a Console link. Widget names are deterministic (`dial_<key>`) and
`offset` values are computed on a grid so the canvas is readable when a customer opens it.

The CR widget's exact JSON type name and property names are not in Twilio's published
schemas. Twilio's documented approach applies: build one widget in the Console, then
`GET /v2/Flows/{sid}` to read the definition and pin the real names. This is a discovery step
in the implementation plan, not an unknown in the design.

### Lambda — `deploy/agentcore_aws_lambda/lambda/`

Two new routes, both handled in the example's `index.py` **before** delegating to
`proxy.lambda_handler`. This ordering matters: `AgentCoreLambdaProxy.lambda_handler`
validates the Twilio signature on every path
(`src/tac_aws/proxy/agentcore_lambda.py:104-110`), and Studio's HTTP Request widget cannot
send one.

- **`POST /session`** — constant-time token compare via `hmac.compare_digest`, extract
  `CallSid`, presign the AgentCore WebSocket URL, return `{"websocket_url": …}`. Rejects
  non-POST and missing or short tokens.
- **`POST /dial`** — Twilio-signature validated, because TwiML Redirect requests are signed.
  Looks the intent up in an env-supplied destination map and returns `<Dial>` TwiML with
  `sendDigits`.

`/twiml` and `/webhook` remain as the library provides them; `/webhook` is still the SMS path.

**No changes to `src/tac_aws`.** `TACAgentCoreApp` already accepts `welcome_message`, and both
channels stay in use, so nothing in the library needs to move.

Studio's HTTP Request widget supports no custom headers, so `/session` is authenticated with
a shared `IVR_SESSION_TOKEN`: generated by the wizard into `.env`, passed to the Lambda by
CDK, and embedded in the flow definition by the generator. The token is visible to anyone who
can read the flow in the Console; all it yields is a presigned WebSocket URL scoped to one
call session. Rotate by clearing the line and re-running `make configure` then `make deploy`.

### CDK and Makefile

- `make build` copies `ivr-config.json` into `agent/` so it ships in the AgentCore code bundle.
- CDK reads `ivr-config.json` to derive the Lambda's extension destination map and passes
  `IVR_SESSION_TOKEN` through from `.env`.
- `make configure` starts the wizard.
- `make deploy` runs the existing stacks, then `preflight`, then `studio-deploy`.
- `make capture-rules` opt-in: adds the `VOICE` and `SMS` capture rules to the chosen
  configuration.
- `make destroy` additionally deletes the Studio flow and clears the number's voice webhook.

## Error handling

| Failure | Behavior |
| --- | --- |
| `/session` non-2xx, or past Studio's 10 s HTTP cap | `get_session` fail → `dial_fallback` |
| CR WebSocket won't connect, or AgentCore cold-start failure | CR widget `failed` → `dial_fallback` |
| Capture rule missing or lagging past the ~3.75 s poll window | `_initialize_conversation` raises → socket closes → CR `failed` → `dial_fallback` |
| `HandoffData` empty or an unrecognized slug | `split-based-on` default → `dial_fallback` |
| Agent never transfers and the caller hangs up | Execution ends normally |
| Destination busy or no answer | Short "couldn't connect" message, then hang up |
| `/dial` receives an unknown intent | `<Say>` plus `<Hangup>`, logged — never a 500 into a live call |
| Bad Twilio credentials in the wizard | Inline 401 in the page; nothing written to disk |
| Flows API rejects the CR widget JSON | Generator prints the API error verbatim |
| Invalid `ivr-config.json` | Generator fails before touching Twilio, with field-level errors |

No caller reaches a dead line: every failure path terminates at the fallback destination or an
explicit spoken message.

## Testing

Tests live in `tests/ivr/` because root `pytest` has `testpaths = ["tests"]`, so that is what
CI runs. A `conftest.py` adds the example directories to `sys.path`. Only pure logic is
tested — nothing that imports `agent/main.py`, which reaches Secrets Manager at import time.

- `flow_builder` snapshots: phone-only, SIP with headers, extension producing a
  `add-twiml-redirect`, fallback wiring, unique widget names, and every transition targeting
  a state that exists.
- Config validation: duplicate keys, bad E.164, non-`X-` SIP headers, missing fallback,
  over-length prompt.
- Prompt rendering: intent catalog present, business prompt included.
- `transfer_call`: sets `pending_handoff_data` to the right slug; rejects unknown intents.
- `/session`: 403 on missing or wrong token; happy path returns a URL with the presigner mocked.
- `/dial`: `sendDigits` formatting, TwiML per destination type, unknown intent handling.
- `preflight`: passes on a matching rule and on `*`; fails with a useful message when absent.

CI runs `ruff check .` and `ruff format --check .` across the whole repo including `deploy/`,
so all new code must be ruff-clean at line length 100. `mypy` covers only `src/tac_aws` and
`getting_started`; that scope stays as is, but new code is written fully typed.

Manual verification checklist goes in the README, since calls cannot be placed from CI:
call the number and ask for billing, hear the confirmation, land on the extension; ask
something nonsensical and land on the operator; confirm the Studio execution log and the
CloudWatch log groups.

## Documentation

- Rewrite `deploy/agentcore_aws_lambda/README.md` for the IVR story: new mermaid diagram, a
  `configure → bootstrap → deploy` quick start, the capture-rule prerequisite, and a
  troubleshooting entry for `Expected exactly 1 conversation for call_sid …` pointing at the
  capture rule.
- `docs/deploy/agentcore_aws_lambda/README.md` is a one-line `--8<--` include and needs no
  edit. Per `CLAUDE.md`, repo-only paths inside the README must use absolute GitHub URLs so
  the links survive inclusion into the site.
- Update the `deploy/README.md` index entry.

## Out of scope

- Hosting the wizard; it is local-only.
- Buying phone numbers or creating Conversation Orchestrator configurations.
- Business-hours routing, holiday schedules, queueing, or voicemail.
- Flex or TaskRouter handoff; destinations are dial targets.
- Changes to `src/tac_aws`.
