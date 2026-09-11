# -*- coding: utf-8 -*-
"""Distillation stage: cards, thinking layer, claims, evidence, desensitization."""
from .technique_cards import TechniqueCard, EvidenceItem
from .thinking_layer import ThinkingLayer
from .claims import Claim, validate_claims
from .writer_contract import WriterContract
from .desensitize import (
    extract_proper_noun_candidates,
    apply_desensitization,
    validate_desensitization,
    compute_work_id,
    scan_artifact,
)
from .evidence import (
    create_chunks,
    expand_evidence_refs,
    extract_candidate_evidence_pool,
    verify_evidence_item,
    verify_all_cards_evidence,
)

__all__ = [
    "TechniqueCard",
    "EvidenceItem",
    "ThinkingLayer",
    "Claim",
    "validate_claims",
    "WriterContract",
    "extract_proper_noun_candidates",
    "apply_desensitization",
    "validate_desensitization",
    "compute_work_id",
    "scan_artifact",
    "create_chunks",
    "expand_evidence_refs",
    "extract_candidate_evidence_pool",
    "verify_evidence_item",
    "verify_all_cards_evidence",
]
