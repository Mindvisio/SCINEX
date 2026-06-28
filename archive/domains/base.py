"""Domain presets: pluggable schema focus + identifier schemes + validators/tools per area.
Core pipeline is domain-agnostic; a preset specializes extraction + validation + analysis.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from extraction.schema import ExtractedRecord, EntityType


@dataclass
class DomainPreset:
    name: str
    description: str = ""
    focus_types: list = field(default_factory=list)   # list[EntityType] the extractor prioritizes
    entity_kinds: list = field(default_factory=list)   # entity.type values this domain expects (str)
    id_schemes: list = field(default_factory=list)     # recognized identifier schemes (str)
    extract_hint: str = ""                             # appended to the extractor prompt
    validators: dict = field(default_factory=dict)      # entity_kind (str) -> Callable[[rec], rec]
    vocab: dict = field(default_factory=dict)

    def validate(self, rec: ExtractedRecord) -> ExtractedRecord:
        """Apply this domain's validator for an ENTITY of a recognized kind (molecule->RDKit)."""
        if rec.entity_type == EntityType.ENTITY:
            fn = self.validators.get((rec.normalized or {}).get("type"))
            if fn:
                return fn(rec)
        return rec


REGISTRY: dict = {}


def register(preset: DomainPreset) -> DomainPreset:
    REGISTRY[preset.name] = preset
    return preset


def get(name: Optional[str]) -> Optional[DomainPreset]:
    return REGISTRY.get(name) if name else None
