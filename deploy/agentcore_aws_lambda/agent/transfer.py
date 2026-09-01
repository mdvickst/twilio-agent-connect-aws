"""The transfer tool that hands a caller off to a configured destination.

Setting ``session.pending_handoff_data`` is TAC's supported hook for a custom
handoff (see ``tac/tools/handoff.py``): the voice channel sends the
ConversationRelay ``end`` message carrying this payload *after* the agent's final
response has been spoken, so the caller hears "connecting you to Billing" and
then gets transferred. The Studio flow splits on the slug.
"""

from __future__ import annotations

from typing import Any, Literal

from ivr_config import FALLBACK_KEY
from tac.models.handoff import PendingHandoffData
from tac.models.session import ConversationSession


def create_transfer_tool(session: ConversationSession, intent_keys: list[str]) -> Any:
    """Create a Strands tool that transfers the caller to a configured destination.

    Args:
        session: The live conversation session for this call. This is the same
            object TAC's voice channel reads when deciding whether to send the
            ConversationRelay ``end`` message, so mutating it here is what
            triggers the transfer.
        intent_keys: Configured intent keys, excluding the fallback.

    Returns:
        A Strands ``DecoratedFunctionTool`` named ``transfer_call``, ready for an
        agent's ``tools`` list.
    """
    from strands import tool

    allowed = (*intent_keys, FALLBACK_KEY)

    def transfer_call(intent: str) -> dict[str, str]:
        """Transfers the caller to the department that handles the given intent.

        Call this as soon as you know where the caller belongs. Say one short
        sentence naming the destination in the same turn — the caller hears it
        before the transfer happens.

        Args:
            intent: Which configured destination to transfer the caller to.

        Returns:
            Dictionary with the transfer status and the resolved intent.
        """
        if intent not in allowed:
            msg = f"Unknown intent {intent!r}. Must be one of: {', '.join(allowed)}"
            raise ValueError(msg)

        session.pending_handoff_data = PendingHandoffData(handoff_data=intent)
        return {"status": "transfer_initiated", "intent": intent}

    # Narrow the annotation to the configured keys so the generated tool schema
    # carries an enum. Strands builds inputSchema from the type hints, so this
    # must happen before decorating.
    transfer_call.__annotations__["intent"] = Literal[allowed]  # type: ignore[valid-type]

    return tool(transfer_call)
