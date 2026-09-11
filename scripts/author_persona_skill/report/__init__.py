# -*- coding: utf-8 -*-
"""Report stage: templates, validation gates, quality scoring, repair, rendering."""
from .templates import MASTER_SYSTEM_PROMPT, build_analysis_prompt
from .renderer import extract_json_block, render_report_outputs
from .validator import validate_report
from .health import check_response_health
from .quality import assess_quality, assess_quality_gate, quality_notes
from .repair import attach_repair, build_repair_brief, build_repair_prompt
from .metrics import METRIC_VERSION, build_metric_registry

__all__ = [
    "MASTER_SYSTEM_PROMPT",
    "build_analysis_prompt",
    "extract_json_block",
    "render_report_outputs",
    "validate_report",
    "check_response_health",
    "assess_quality",
    "assess_quality_gate",
    "quality_notes",
    "attach_repair",
    "build_repair_brief",
    "build_repair_prompt",
    "METRIC_VERSION",
    "build_metric_registry",
]
