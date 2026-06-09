"""
conftest.py — pytest root configuration.

Ensures the cotizador project root is on sys.path so that
`from core.db import ...` and `from procedures.rules import ...`
resolve correctly regardless of how pytest is invoked (single file
or full suite). Required because tests/__init__.py makes pytest treat
tests/ as a package, which suppresses pytest's automatic path insertion.
"""

import sys
from pathlib import Path

# Insert the cotizador root (this file's directory) at the front of sys.path.
# This is idempotent — inserting the same path twice does no harm.
_ROOT = str(Path(__file__).parent.resolve())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
