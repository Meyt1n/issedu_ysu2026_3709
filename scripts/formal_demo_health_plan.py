"""Re-export formal demo plan from the API package for CLI scripts."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_API = _ROOT / "src" / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from app.formal_demo_plan import *  # noqa: F401,F403
