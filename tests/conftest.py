"""Pytest configuration: make the project root importable for the test modules."""

import sys
from pathlib import Path

# The application modules live at the repository root (flat layout), so ensure
# it is on sys.path regardless of where pytest is invoked from.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
