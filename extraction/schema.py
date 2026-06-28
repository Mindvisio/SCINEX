"""scinex extraction schema — the substrate. See SPEC.md section 3.

EntityType now holds five STRUCTURAL, domain-agnostic record types (name kept for compat).
Domain specifics (molecule, reaction, gene, organism, ...) are NOT enum members — they are
entity.type strings + per-scheme identifiers, specialized by the active domain preset (domains/).
"""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Structural record types (domain-agnostic). normalized payload per type:

    ENTITY      {name, type, identifiers:{scheme:value}, formats:{fmt:payload|url}}
                type = domain kind ("molecule","reaction","gene","organism","disease",...).
    RELATION    {subject, relation, object, direction, context:{...}}   (e.g. context.model_organism)
    CLAIM       {statement, subject, predicate, object, polarity:+1|-1|0, retracted}
    METHOD      {name, category, software, params:{...}}   (functional/basis/forcefield | tool/ref)
    MEASUREMENT {metric, conditions:{...}}                 (number in top-level quantity+unit)
    """
    ENTITY = "entity"
    RELATION = "relation"
    CLAIM = "claim"
    METHOD = "method"
    MEASUREMENT = "measurement"


class ValidationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PASSED = "passed"
    FAILED = "failed"
    CONFLICT = "conflict"


class PaperRef(BaseModel):
    paper_id: str
    doi: Optional[str] = None
    title: Optional[str] = None


class Span(BaseModel):
    """Provenance. quote MUST be a verbatim substring of the source text."""
    quote: str
    section: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

    def grounded(self) -> bool:
        return self.char_start is not None and self.char_end is not None


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


_ID_PRIORITY = ("inchikey", "inchi", "smiles", "pubchem_cid", "chembl",
                "uniprot", "pdb_id", "ensembl", "hgnc", "ncbi_gene", "cas", "taxon")


def _entity_id(n: dict, value: str) -> str:
    """Best stable identity for an entity: a canonical/xref identifier, else the name."""
    ids = (n or {}).get("identifiers") or {}
    for scheme in _ID_PRIORITY:
        if ids.get(scheme):
            return f"{scheme}:{str(ids[scheme]).lower()}"
    return _norm((n or {}).get("name") or value)


class ExtractedRecord(BaseModel):
    record_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    paper: PaperRef
    entity_type: EntityType                      # structural record type (see EntityType)
    value: str                                   # short human-readable label
    normalized: dict[str, Any] = Field(default_factory=dict)
    quantity: Optional[float] = None
    unit: Optional[str] = None
    span: Optional[Span] = None
    extractor: str = ""
    confidence: float = 0.5
    validation: ValidationStatus = ValidationStatus.UNVERIFIED
    validation_detail: Optional[str] = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def key(self) -> tuple:
        """Identity for cross-model merge + gold matching. Mirror eval/run_eval._gold_key."""
        n = self.normalized
        et = self.entity_type
        tag = et.value
        if et == EntityType.ENTITY:
            return (tag, n.get("type") or "", _entity_id(n, self.value))
        if et == EntityType.RELATION:
            return (tag, _norm(n.get("subject")), _norm(n.get("relation")), _norm(n.get("object")))
        if et == EntityType.CLAIM:
            return (tag, _norm(n.get("subject")), _norm(n.get("predicate")),
                    _norm(n.get("object")), n.get("polarity"))
        if et == EntityType.METHOD:
            return (tag, _norm(n.get("name")), _norm((n.get("params") or {}).get("functional")))
        return (tag, _norm(n.get("metric") or self.value), self.unit)  # MEASUREMENT


# ---- raw LLM extraction output (validated by call_json before quote-grounding) ----
from typing import Any as _Any, Optional as _Optional


class RawRecord(BaseModel):
    entity_type: str
    value: str = ''
    normalized: dict[str, _Any] = Field(default_factory=dict)
    quantity: _Optional[float] = None
    unit: _Optional[str] = None
    quote: str = ''
    confidence: float = 0.5


class RawExtraction(BaseModel):
    records: list[RawRecord] = Field(default_factory=list)
