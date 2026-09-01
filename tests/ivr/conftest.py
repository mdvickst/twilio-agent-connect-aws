"""Path setup for the AI IVR example tests.

The example is not an installed package. `agent/` holds the canonical config
model plus the prompt and transfer modules; the example root holds the `studio`,
`wizard`, and `lambda` packages. Both go on sys.path so tests can import them
the same way the deployed code does.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "deploy" / "agentcore_aws_lambda"
_AGENT_DIR = _EXAMPLE_ROOT / "agent"

for _path in (_EXAMPLE_ROOT, _AGENT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
