"""One-liner sys.path bootstrap for scripts. Usage: import _bootstrap

Works when executed directly (python scripts/foo.py — Python adds scripts/
to sys.path[0]) and when imported via pytest (conftest adds scripts/ first).
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
