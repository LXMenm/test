"""Pytest bootstrap for repository-local imports.

Ensures project root is importable even when pytest collection starts from
a nested test directory (e.g. check_c/).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)
