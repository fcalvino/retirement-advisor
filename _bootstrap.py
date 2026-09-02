"""One-liner sys.path bootstrap for scripts. Usage: import _bootstrap

Keeps scripts/ clean of boilerplate. Works when imported directly (python
scripts/foo.py) or as a package member (pytest imports scripts.foo).
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
