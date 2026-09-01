"""Local configuration wizard for the AI IVR example.

Puts the sibling ``agent/`` directory on sys.path so the wizard validates against
the same config model the deployed agent uses, rather than a copy.
"""

from __future__ import annotations

import sys
from pathlib import Path

_AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))
