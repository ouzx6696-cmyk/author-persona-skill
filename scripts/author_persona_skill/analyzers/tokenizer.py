# -*- coding: utf-8 -*-
"""Segmentation / POS adapter with graceful degradation.

Low-level measurement (named entities, the five worldview vocabulary classes,
part-of-speech ratios) reads best with a real Chinese tokenizer, so the skill
ships a trimmed pure-Python ``jieba`` under ``libs/``. That copy is **optional
at runtime**: if it is missing or fails to load, this adapter falls back to a
deterministic regex approximation and reports ``available=False`` so callers can
downgrade their wording (see ``references/quality-baseline.md`` §4: direct
measurement vs heuristic vs weak signal).

Contract: never raise, never return a partial type. A missing tokenizer degrades
a *metric*, it must not fail an analysis run.
"""
from __future__ import annotations

import re
import warnings
from typing import Any, Dict, List, Optional, Tuple

#: A 2+ character CJK run. Used only by the fallback path.
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fa5]{2,}")
_CJK_SINGLE_RE = re.compile(r"[\u4e00-\u9fa5]")

_jieba_mod = None
_posseg_mod = None
_load_attempted = False
_load_error: Optional[str] = None


def _attempt_load() -> None:
    """Import the vendored jieba once. Failure is recorded, never raised."""
    global _jieba_mod, _posseg_mod, _load_attempted, _load_error
    if _load_attempted:
        return
    _load_attempted = True
    try:
        # Make sure libs/ is on sys.path even if the caller imported this module
        # directly (bypassing the package __init__ bootstrap).
        from .._vendor import ensure_libs_on_path

        ensure_libs_on_path()
        # Upstream jieba 0.42.1 still uses non-raw regex literals, which Python
        # 3.12 reports as SyntaxWarning on first import. The patterns are
        # harmless (the escapes are valid), but the noise would land in CLI
        # stderr and agent transcripts, so it is muted narrowly around the
        # import rather than globally.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            import jieba  # type: ignore
            import jieba.posseg as _pseg  # type: ignore

        _jieba_mod = jieba
        _posseg_mod = _pseg
    except Exception as exc:  # noqa: BLE001 - absence is a supported state
        _load_error = f"{type(exc).__name__}: {exc}"


def tokenizer_available() -> bool:
    """Whether a real tokenizer (vendored jieba) loaded successfully."""
    _attempt_load()
    return _jieba_mod is not None


def tokenizer_status() -> Dict[str, Any]:
    """Machine-readable availability record for provenance / diagnostics."""
    _attempt_load()
    return {
        "tokenizer": "jieba(0.42.1, vendored)" if tokenizer_available() else "regex-fallback",
        "available": tokenizer_available(),
        "pos_available": _posseg_mod is not None,
        "error": _load_error,
    }


def cut(text: str) -> List[str]:
    """Split text into words.

    Without a tokenizer, each maximal CJK run is split into overlapping 2-grams
    (the standard fallback for Chinese type/token statistics) plus any trailing
    odd character. That keeps a usable token count and TTR, at the cost of
    inflating the type count -- which is exactly why callers must label derived
    metrics as weak signal.
    """
    if not text:
        return []
    _attempt_load()
    if _jieba_mod is not None:
        try:
            return [w for w in _jieba_mod.cut(text) if w.strip()]
        except Exception:  # noqa: BLE001 - degrade rather than fail the run
            pass
    tokens: List[str] = []
    for match in _CJK_RUN_RE.finditer(text):
        run = match.group(0)
        for i in range(len(run) - 1):
            tokens.append(run[i:i + 2])
        if len(run) % 2 == 1:
            tokens.append(run[-1])
    return tokens


def posseg(text: str) -> List[Tuple[str, str]]:
    """Return ``(word, pos_flag)`` pairs.

    With no tokenizer the flag is a coarse guess: a 2+ character run becomes
    ``"n"`` (noun-ish) and single characters carry no flag. Callers must treat
    flags as weak signal in that case.
    """
    if not text:
        return []
    _attempt_load()
    if _posseg_mod is not None:
        try:
            return [(pair.word, pair.flag) for pair in _posseg_mod.cut(text)]
        except Exception:  # noqa: BLE001
            pass
    out: List[Tuple[str, str]] = []
    for match in _CJK_RUN_RE.finditer(text):
        out.append((match.group(0), "n"))
    for single in _CJK_SINGLE_RE.finditer(text):
        out.append((single.group(0), ""))
    return out


def words_with_flag(text: str, flags: Tuple[str, ...]) -> List[str]:
    """Return words whose POS flag starts with any of ``flags``.

    Note: jieba emits compound flags such as ``nr``/``ns``/``nt``/``nz``, so
    membership is prefix-based, not equality-based.
    """
    if not flags:
        return []
    return [word for word, flag in posseg(text) if flag and flag.startswith(flags)]


def is_degraded() -> bool:
    """True when measurements must be labelled as weak signal."""
    return not tokenizer_available()
