# -*- coding: utf-8 -*-
"""Vendored-dependency bootstrap.

The skill ships a trimmed, pure-Python copy of ``jieba`` (segmentation +
part-of-speech tagging) so that named entities, the five worldview vocabulary
classes and part-of-speech ratios can be measured without asking the user to
install anything.

Import-order contract (same shape as ``_version.py``): this module must import
**standard library only** and must never import another module of this package.
``author_persona_skill/__init__.py`` calls :func:`ensure_libs_on_path` as its
first statement, before ``_api`` pulls in the analyzers, so any intra-package
import here would re-enter a half-initialised package.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

#: Relative marker identifying a usable candidate directory: it must contain
#: ``jieba/__init__.py`` directly, i.e. be a sys.path *root* rather than the
#: package directory itself.
_PROBE = Path("jieba") / "__init__.py"

_cached_libs_path: Optional[str] = None
_probed = False


def libs_candidates() -> List[Path]:
    """Return search roots for the vendored libraries, most specific first.

    Two deployment layouts are supported:

    1. **package-local** ``<pkg>/_vendored`` — used by a non-editable wheel,
       which maps ``libs/`` into ``author_persona_skill/_vendored``. Keeping it
       under our own package namespace avoids polluting site-packages with a
       top-level ``jieba`` that could shadow (or be shadowed by) a real install.
    2. **skill-root** ``<root>/libs`` — the repo checkout and the unzipped
       skill archive, where ``<root>`` is the directory holding ``SKILL.md``.

    A bounded upward walk is appended as a safety net for unusual nesting.
    """
    pkg_dir = Path(__file__).resolve().parent
    candidates: List[Path] = [pkg_dir / "_vendored"]

    # pkg_dir = <root>/scripts/author_persona_skill
    #   parents[0] = <root>/scripts
    #   parents[1] = <root>
    for parent in list(pkg_dir.parents)[:2]:
        candidates.append(parent / "libs")

    current = pkg_dir
    for _ in range(4):
        current = current.parent
        candidates.append(current / "libs")

    seen = set()
    unique: List[Path] = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def find_libs_path() -> Optional[str]:
    """Return the first candidate directory that actually holds vendored libs."""
    for candidate in libs_candidates():
        if (candidate / _PROBE).is_file():
            return str(candidate)
    return None


def ensure_libs_on_path() -> Optional[str]:
    """Put the vendored-libs directory on ``sys.path`` exactly once.

    Idempotent and cheap: the probe runs at most once per process. Inserted at
    position 0 so the vendored copy is chosen deterministically even when the
    interpreter happens to have a different jieba installed.
    """
    global _cached_libs_path, _probed
    if not _probed:
        _cached_libs_path = find_libs_path()
        _probed = True
    if _cached_libs_path and _cached_libs_path not in sys.path:
        sys.path.insert(0, _cached_libs_path)
    return _cached_libs_path


def vendored_libs_available() -> bool:
    """Whether a vendored-libs directory was found."""
    ensure_libs_on_path()
    return _cached_libs_path is not None
