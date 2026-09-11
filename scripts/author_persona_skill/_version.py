# -*- coding: utf-8 -*-
"""Single runtime source of truth for the package version.

This file has two shapes:

1. Source tree / editable install (this file as committed):
   ``VERSION`` is ``None`` and the version is resolved at import time from
   ``<skill root>/pyproject.toml`` (two directories up).
2. Inside a built wheel:
   ``build_backend`` rewrites the marker line below into ``VERSION = "x.y.z"``,
   because a non-editable install ships no pyproject.toml at all.

CONTRACT — do not add imports from ``author_persona_skill`` here.
``report/renderer.py`` imports this module while the package ``__init__`` is
still executing (``__init__`` -> ``pipeline`` -> ``renderer``), so any
intra-package import from this file would deadlock. Standard library only.
"""
from __future__ import annotations

from pathlib import Path

# build_backend replaces this exact line when building a wheel. Do not reformat.
VERSION = None  # __BURN_VERSION__

# Honest "unknown" marker. Deliberately NOT a stale release number: a wrong
# number risks a silent contract mismatch downstream (novel-writer reads
# report.json["schema_version"]), whereas 0.0.0 is obviously unresolved.
_UNRESOLVED = "0.0.0"


def _resolve() -> str:
    if VERSION:
        return str(VERSION)
    try:
        import tomllib

        pyproj = Path(__file__).resolve().parents[2] / "pyproject.toml"
        return str(tomllib.loads(pyproj.read_text(encoding="utf-8"))["project"]["version"])
    except Exception:
        return _UNRESOLVED


__version__ = _resolve()
