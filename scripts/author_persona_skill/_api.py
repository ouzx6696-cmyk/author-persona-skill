# -*- coding: utf-8 -*-
"""The public API surface, defined once.

Two entry points re-export this module instead of maintaining parallel import
lists (they used to drift):

* ``scripts/author_persona_skill/__init__.py`` — the installed package.
* ``__init__.py`` at the skill root — a shim for the unzipped-skill layout,
  where the skill directory itself sits on ``sys.path``.

Keep this module free of side effects: it only re-exports names.
"""
from __future__ import annotations

from ._version import __version__
from .contracts import describe_prepare_contract, validate_prepare_result
from .pipeline import (
    prepare_analysis,
    finalize_analysis,
    process_large_file,
    analyze_style,
)
from .fidelity.fidelity_check import (
    run_fidelity_check,
    check_copy_risk,
    derive_dynamic_tolerances,
)
from .distill.technique_cards import TechniqueCard
from .distill.thinking_layer import ThinkingLayer
from .distill.claims import Claim
from .distill.desensitize import compute_work_id, scan_artifact
from .report.metrics import build_metric_registry, METRIC_VERSION
from .report.quality import assess_quality
from .report.repair import build_repair_prompt
from .analyzers.style_analyzer import StyleAnalyzer
from .analyzers.dialogue_analyzer import DialogueAnalyzer
from .analyzers.noise import filter_noise

__all__ = [
    "prepare_analysis",
    "finalize_analysis",
    "process_large_file",
    "analyze_style",
    "run_fidelity_check",
    "check_copy_risk",
    "derive_dynamic_tolerances",
    "TechniqueCard",
    "ThinkingLayer",
    "Claim",
    "compute_work_id",
    "scan_artifact",
    "build_metric_registry",
    "METRIC_VERSION",
    "assess_quality",
    "build_repair_prompt",
    "validate_prepare_result",
    "describe_prepare_contract",
    "StyleAnalyzer",
    "DialogueAnalyzer",
    "filter_noise",
    "__version__",
]
