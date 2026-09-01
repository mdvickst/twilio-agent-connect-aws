"""Tests for the IVR transfer tool."""

from __future__ import annotations

import json

import pytest
from tac.models.session import ConversationSession
from transfer import create_transfer_tool


def make_session() -> ConversationSession:
    return ConversationSession(conversation_id="CA" + "1" * 32, channel="voice")


def test_tool_is_named_transfer_call():
    tool = create_transfer_tool(make_session(), ["billing", "sales"])
    assert tool.tool_name == "transfer_call"


def test_schema_constrains_intent_to_configured_keys_plus_fallback():
    tool = create_transfer_tool(make_session(), ["billing", "sales"])
    schema = tool.tool_spec["inputSchema"]["json"]
    assert schema["properties"]["intent"]["enum"] == ["billing", "sales", "fallback"]
    assert schema["required"] == ["intent"]


def test_calling_the_tool_stages_the_handoff_slug_on_the_session():
    session = make_session()
    tool = create_transfer_tool(session, ["billing", "sales"])

    result = tool(intent="billing")

    assert result == {"status": "transfer_initiated", "intent": "billing"}
    assert session.pending_handoff_data is not None
    assert session.pending_handoff_data.handoff_data == "billing"


def test_staged_payload_serializes_to_the_conversationrelay_end_message():
    session = make_session()
    tool = create_transfer_tool(session, ["billing"])

    tool(intent="billing")

    payload = session.pending_handoff_data.model_dump_json(by_alias=True)
    assert json.loads(payload) == {"type": "end", "handoffData": "billing"}


def test_fallback_is_always_a_valid_intent():
    session = make_session()
    tool = create_transfer_tool(session, ["billing"])

    tool(intent="fallback")

    assert session.pending_handoff_data.handoff_data == "fallback"


def test_unknown_intent_is_rejected_and_stages_nothing():
    session = make_session()
    tool = create_transfer_tool(session, ["billing"])

    with pytest.raises(ValueError, match="Unknown intent"):
        tool(intent="mortgages")

    assert session.pending_handoff_data is None
