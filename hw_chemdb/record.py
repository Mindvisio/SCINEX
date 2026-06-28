"""Flat DB-row schema = the CSV contract.

Lecture-aligned: every record keeps the RAW value AND the STANDARDISED value plus the conversion
rule (slide 7), full provenance back to the PDF (slide 2 'source'), a validation verdict
(slides 24-25), and dedup/conflict metadata so conflicts become METADATA, never silently averaged
(slides 21-23). One row = one (compound, property) observation, or a bare compound mention.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import hashlib

# CSV column order (stable public contract)
COLUMNS = [
    "record_id",
    # --- provenance ---
    "source_pdf", "source_page", "source_type",        # source_type: text | table | figure
    "extractor", "evidence",                            # extractor: regex | table | ocsr:<eng> | opsin
    # --- entity (compound) ---
    "name_raw", "name_std",
    "smiles_raw", "smiles_canonical", "inchikey",
    "pubchem_cid", "cas", "formula", "mw", "iupac_name",
    # --- context ---
    "target_raw", "assay_type_raw", "assay_type_std", "organism_raw", "organism_std",
    # --- measurement (raw kept verbatim, std derived, rule documented) ---
    "property", "value_raw", "unit_raw", "value_std", "unit_std",
    "value_min", "value_max", "value_op", "conversion_note",
    # --- validation ---
    "validation", "validation_detail",                  # validation: passed | unverified | failed
    # --- dedup + conflict (metadata, not destructive) ---
    "dup_group", "dup_level", "is_primary",
    "conflict_group", "conflict_flag",
    # --- human-review queue (slide 16: what cannot be auto-resolved) ---
    "needs_review", "review_reason",
    "extracted_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Record:
    source_pdf: str = ""
    source_page: Optional[int] = None
    source_type: str = ""
    extractor: str = ""
    evidence: str = ""
    name_raw: Optional[str] = None
    name_std: Optional[str] = None
    smiles_raw: Optional[str] = None
    smiles_canonical: Optional[str] = None
    inchikey: Optional[str] = None
    pubchem_cid: Optional[str] = None
    cas: Optional[str] = None
    formula: Optional[str] = None
    mw: Optional[float] = None
    iupac_name: Optional[str] = None
    target_raw: Optional[str] = None
    assay_type_raw: Optional[str] = None
    assay_type_std: Optional[str] = None
    organism_raw: Optional[str] = None
    organism_std: Optional[str] = None
    property: Optional[str] = None
    value_raw: Optional[str] = None
    unit_raw: Optional[str] = None
    value_std: Optional[float] = None
    unit_std: Optional[str] = None
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    value_op: Optional[str] = None
    conversion_note: Optional[str] = None
    validation: str = "unverified"
    validation_detail: str = ""
    dup_group: Optional[str] = None
    dup_level: Optional[int] = None
    is_primary: Optional[bool] = None
    conflict_group: Optional[str] = None
    conflict_flag: bool = False
    needs_review: bool = False
    review_reason: str = ""
    extracted_at: str = field(default_factory=_now)
    record_id: str = ""

    def assign_id(self) -> "Record":
        key = "|".join(str(x) for x in (
            self.source_pdf, self.source_page, self.source_type, self.name_raw,
            self.smiles_raw, self.property, self.value_raw, self.unit_raw, (self.evidence or "")[:80]))
        self.record_id = "r_" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:12]
        return self

    def flag_review(self, reason: str) -> "Record":
        self.needs_review = True
        self.review_reason = (self.review_reason + "; " + reason).strip("; ") if self.review_reason else reason
        return self

    def to_row(self) -> dict:
        d = asdict(self)
        return {c: d.get(c) for c in COLUMNS}