"""Studio flow generation for the AI IVR example.

Puts the sibling ``agent/`` directory on sys.path so this package shares the
canonical IVR config model with the AgentCore bundle rather than duplicating it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))
