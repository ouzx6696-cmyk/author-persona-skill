# -*- coding: utf-8 -*-
"""Author Persona Skill test suite.

``tests`` is a package so that ``pytest tests`` and
``python -m unittest discover -s tests -t .`` both resolve imports the same
way: the repository root and ``scripts/`` are put on ``sys.path`` here,
exactly once, before any test module imports the code under test.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"

for _path in (_ROOT, _SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
