"""Generic validator dispatch. Domain-specific checks (e.g. chemistry RDKit/PubChem) live in
domains/ and apply via the active DomainPreset — the core stays domain-agnostic.
"""
from __future__ import annotations
from typing import Optional

from extraction.schema import ExtractedRecord


def validate(rec: ExtractedRecord, domain=None) -> ExtractedRecord:
    """Apply the active domain preset's validators, then generic checks.

    domain: a domains.base.DomainPreset (or None for no domain-specific validation).
    """
    if domain is not None:
        rec = domain.validate(rec)
    # TODO generic checks: property/condition unit sanity; claim/relation schema-key presence.
    return rec
