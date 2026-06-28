"""scinex corpus store -- the structured representation built from ExtractedRecords.

Per-mention ExtractedRecords (extraction/schema.py) collapse here into canonical NODES grouped by
object type, linked by typed EDGES carrying ROLES, every node/edge keeping aggregated PROVENANCE
(paper+span / asset+bbox) + validation + confidence. This is the substrate's serialized form; three
projections consume it -- molecules(), dataset(metric), document_model(). Identity reuses
extraction.schema._entity_id (InChIKey > xref > name): "aspirin" in 5 papers = ONE node, 5
provenance entries -- the records->graph collapse.
"""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import json
from pathlib import Path

from pydantic import BaseModel, Field

from extraction.schema import (ExtractedRecord, EntityType, ValidationStatus, Span,
                               PaperRef, _entity_id, _norm)


class Role(str, Enum):
    """Controlled role vocabulary (Eremeeva mention->type->role; extensible)."""
    REACTANT = "reactant"
    PRODUCT = "product"
    REAGENT = "reagent"
    CATALYST = "catalyst"
    SOLVENT = "solvent"
    REACTION_MEDIUM = "reaction_medium"
    LIGAND = "ligand"
    TARGET = "target"
    ANALYTE = "analyte"            # entity a measurement is about
    PROPERTY = "property"          # measured property name
    OTHER = "other"


class Provenance(BaseModel):
    """Where a fact came from. Every node/edge carries a list of these (one per source mention)."""
    paper_id: str = ""
    span: Optional[Span] = None
    asset_id: Optional[str] = None         # figure/table the fact came from
    bbox: Optional[list[float]] = None
    extractor: str = ""
    confidence: float = 0.5
    validation: ValidationStatus = ValidationStatus.UNVERIFIED
    record_id: Optional[str] = None        # back-link to the source ExtractedRecord
    source_url: Optional[str] = None        # external-DB URL (enrichment provenance)


def _best_validation(vs) -> ValidationStatus:
    order = {ValidationStatus.PASSED: 3, ValidationStatus.CONFLICT: 2,
             ValidationStatus.UNVERIFIED: 1, ValidationStatus.FAILED: 0}
    return max(vs, key=lambda v: order.get(v, 0)) if vs else ValidationStatus.UNVERIFIED


class EntityNode(BaseModel):
    node_id: str                            # _entity_id: "inchikey:..." | "name:..."
    kind: str = "entity"                    # molecule | material | protein | gene | ...
    label: str = ""
    names: list[str] = Field(default_factory=list)
    identifiers: dict[str, Any] = Field(default_factory=dict)   # {scheme: value} merged
    formats: dict[str, Any] = Field(default_factory=dict)       # {smiles, inchi, ...}
    properties: dict[str, Any] = Field(default_factory=dict)    # physico-chem props (mw, mp, logP...)
    provenance: list[Provenance] = Field(default_factory=list)
    validation: ValidationStatus = ValidationStatus.UNVERIFIED
    confidence: float = 0.5


class MeasurementNode(BaseModel):
    node_id: str
    metric: str = ""
    value: Optional[float] = None
    unit: Optional[str] = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    of_entity: Optional[str] = None         # node_id of the analyte entity
    provenance: list[Provenance] = Field(default_factory=list)
    validation: ValidationStatus = ValidationStatus.UNVERIFIED
    confidence: float = 0.5


class MethodNode(BaseModel):
    node_id: str
    name: str = ""
    category: Optional[str] = None
    software: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)
    confidence: float = 0.5


class ClaimNode(BaseModel):
    node_id: str
    statement: str = ""
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    polarity: int = 0
    retracted: bool = False
    provenance: list[Provenance] = Field(default_factory=list)
    confidence: float = 0.5


class AssetNode(BaseModel):
    """Figure or table. Carries the Eremeeva figure-JSON fields (entities, data_relevance)."""
    node_id: str                            # fig_id / table_id
    kind: str = "figure"                    # figure | table
    paper_id: str = ""
    page: Optional[int] = None
    bbox: Optional[list[float]] = None
    image_path: Optional[str] = None
    caption: str = ""
    text: Optional[str] = None              # table markdown
    entities: list[str] = Field(default_factory=list)   # node_ids in caption + surrounding text
    data_relevance: Optional[str] = None    # binding_curve | structure | spectrum | ...
    provenance: list[Provenance] = Field(default_factory=list)


class PaperNode(BaseModel):
    paper_id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    sections: list[str] = Field(default_factory=list)    # reading order (GROBID, later)
    references: list[str] = Field(default_factory=list)  # cited paper_ids/DOIs (citation graph)


class RelationEdge(BaseModel):
    subject: str                            # node_id (or normalized name if unresolved)
    predicate: str = ""                     # reacts_with | inhibits | measured_as | depicted_in
    object: str = ""                        # node_id (or normalized name)
    role: Optional[Role] = None             # role of subject in the relation
    context: dict[str, Any] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)
    confidence: float = 0.5


class CorpusStore(BaseModel):
    """The structured corpus file: typed node groups + relation edges. Serializes to one JSON, or to
    per-group JSONL (dataset-friendly). Projections: molecules / dataset / document_model."""
    domain: str = "chemistry"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    papers: dict[str, PaperNode] = Field(default_factory=dict)
    entities: dict[str, EntityNode] = Field(default_factory=dict)
    measurements: list[MeasurementNode] = Field(default_factory=list)
    methods: list[MethodNode] = Field(default_factory=list)
    claims: list[ClaimNode] = Field(default_factory=list)
    assets: list[AssetNode] = Field(default_factory=list)
    relations: list[RelationEdge] = Field(default_factory=list)

    def stats(self) -> dict:
        return {"papers": len(self.papers), "entities": len(self.entities),
                "molecules": sum(1 for e in self.entities.values() if e.kind == "molecule"),
                "measurements": len(self.measurements), "methods": len(self.methods),
                "claims": len(self.claims), "assets": len(self.assets),
                "relations": len(self.relations)}

    # -- serialization --
    def to_json(self) -> dict:
        return self.model_dump(mode="json")

    def save(self, path) -> str:
        Path(path).write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2),
                              encoding="utf-8")
        return str(path)

    @classmethod
    def load(cls, path) -> "CorpusStore":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def to_jsonl(self, out_dir) -> dict:
        """One JSONL per group (each row a node/edge). Returns {group: path}."""
        out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
        groups = {"papers": list(self.papers.values()), "entities": list(self.entities.values()),
                  "measurements": self.measurements, "methods": self.methods,
                  "claims": self.claims, "assets": self.assets, "relations": self.relations}
        paths = {}
        for name, items in groups.items():
            fp = out / f"{name}.jsonl"
            with open(fp, "w", encoding="utf-8") as f:
                for it in items:
                    f.write(json.dumps(it.model_dump(mode="json"), ensure_ascii=False) + "\n")
            paths[name] = str(fp)
        return paths

    # -- projections --
    def molecules(self) -> list:
        """Deduped molecule nodes (research / substructure / structure dataset)."""
        return [e for e in self.entities.values() if e.kind == "molecule"]

    def dataset(self, metric: Optional[str] = None) -> list:
        """Flat measurement rows joined to analyte entity + conditions + role. CSV/pandas-ready."""
        rows = []
        for m in self.measurements:
            if metric and _norm(m.metric) != _norm(metric):
                continue
            ent = self.entities.get(m.of_entity) if m.of_entity else None
            role = None
            if m.of_entity:
                for r in self.relations:
                    if r.subject == m.of_entity and r.role:
                        role = r.role.value
                        break
            row = {"metric": m.metric, "value": m.value, "unit": m.unit,
                   "entity": ent.label if ent else None,
                   "inchikey": (ent.identifiers.get("inchikey") if ent else None),
                   "smiles": (ent.formats.get("smiles") if ent else None),
                   "role": role, "validation": m.validation.value,
                   "paper_id": (m.provenance[0].paper_id if m.provenance else None)}
            row.update({f"cond.{k}": v for k, v in (m.conditions or {}).items()})
            rows.append(row)
        return rows

    def document_model(self) -> dict:
        """Skeleton for compiling/rendering a new document: papers (sections, refs) + assets per
        paper + a citation edge list. Sections/refs fill in once GROBID lands."""
        assets_by_paper: dict = {}
        for a in self.assets:
            assets_by_paper.setdefault(a.paper_id, []).append(a.node_id)
        cites = [{"from": p.paper_id, "to": ref}
                 for p in self.papers.values() for ref in p.references]
        return {"papers": [p.model_dump(mode="json") for p in self.papers.values()],
                "assets_by_paper": assets_by_paper, "citations": cites}
