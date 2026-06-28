"""Build a CorpusStore from ExtractedRecords (+ figure/table asset dicts). The records->graph
collapse: dedup entities by identity, group measurements/methods/claims, lift RELATION records to
typed edges with roles, ingest assets. Two passes so measurement/relation entity refs resolve
against the COMPLETE entity set (order-independent). Reuses extraction.schema identity helpers.
"""
from __future__ import annotations
from typing import Optional
import uuid

from extraction.schema import ExtractedRecord, EntityType, PaperRef, _entity_id, _norm
from store.schema import (CorpusStore, EntityNode, MeasurementNode, MethodNode, ClaimNode,
                          AssetNode, PaperNode, RelationEdge, Role, Provenance, _best_validation)

_ROLE_ALIASES = {
    "reactant": Role.REACTANT, "substrate": Role.REACTANT, "starting material": Role.REACTANT,
    "product": Role.PRODUCT, "reagent": Role.REAGENT, "catalyst": Role.CATALYST,
    "solvent": Role.SOLVENT, "reaction medium": Role.REACTION_MEDIUM,
    "medium": Role.REACTION_MEDIUM, "ligand": Role.LIGAND, "target": Role.TARGET,
    "analyte": Role.ANALYTE, "property": Role.PROPERTY,
}


def _role(s) -> Optional[Role]:
    return _ROLE_ALIASES.get(_norm(s)) if s else None


def _prov(rec: ExtractedRecord) -> Provenance:
    n = rec.normalized or {}
    return Provenance(paper_id=rec.paper.paper_id, span=rec.span,
                      asset_id=n.get("figure"), bbox=n.get("bbox"),
                      extractor=rec.extractor, confidence=rec.confidence,
                      validation=rec.validation, record_id=rec.record_id)


def _resolve(store: CorpusStore, name) -> Optional[str]:
    """Resolve a free-text entity reference to an existing entity node_id (id-key, then name)."""
    if not name:
        return None
    key = _entity_id({"name": name}, name)
    if key in store.entities:
        return key
    nm = _norm(name)
    for nid, e in store.entities.items():
        if _norm(e.label) == nm or nm in [_norm(x) for x in e.names]:
            return nid
    return None


def build_store(records, *, assets=None, papers=None, domain="chemistry") -> CorpusStore:
    store = CorpusStore(domain=domain)

    def _add_paper(pr: PaperRef):
        if pr and pr.paper_id not in store.papers:
            store.papers[pr.paper_id] = PaperNode(paper_id=pr.paper_id, doi=pr.doi, title=pr.title)

    for pr in (papers or []):
        _add_paper(pr)
    records = list(records or [])
    for rec in records:
        _add_paper(rec.paper)

    # -- pass 1: entities (dedup by identity, merge ids/names/formats/provenance) --
    for rec in records:
        if rec.entity_type != EntityType.ENTITY:
            continue
        n = rec.normalized or {}
        nid = _entity_id(n, rec.value)
        e = store.entities.get(nid)
        if e is None:
            e = EntityNode(node_id=nid, kind=(n.get("type") or "entity"),
                           label=(n.get("name") or rec.value))
            store.entities[nid] = e
        nm = n.get("name") or rec.value
        if nm and nm not in e.names:
            e.names.append(nm)
        for scheme, val in (n.get("identifiers") or {}).items():
            e.identifiers.setdefault(scheme, val)
        for fmt, val in (n.get("formats") or {}).items():
            e.formats.setdefault(fmt, val)
        e.provenance.append(_prov(rec))
        e.validation = _best_validation([e.validation, rec.validation])
        e.confidence = max(e.confidence, rec.confidence)

    # -- pass 2: measurements / methods / claims / relations (resolve entity refs) --
    for rec in records:
        et = rec.entity_type
        if et == EntityType.ENTITY:
            continue
        n = rec.normalized or {}
        prov = _prov(rec)
        if et == EntityType.MEASUREMENT:
            store.measurements.append(MeasurementNode(
                node_id=uuid.uuid4().hex, metric=(n.get("metric") or rec.value),
                value=rec.quantity, unit=rec.unit, conditions=(n.get("conditions") or {}),
                of_entity=_resolve(store, n.get("analyte") or n.get("entity") or n.get("compound")),
                provenance=[prov], validation=rec.validation, confidence=rec.confidence))
        elif et == EntityType.METHOD:
            store.methods.append(MethodNode(
                node_id=uuid.uuid4().hex, name=(n.get("name") or rec.value),
                category=n.get("category"), software=n.get("software"),
                params=(n.get("params") or {}), provenance=[prov], confidence=rec.confidence))
        elif et == EntityType.CLAIM:
            store.claims.append(ClaimNode(
                node_id=uuid.uuid4().hex, statement=(n.get("statement") or rec.value),
                subject=n.get("subject"), predicate=n.get("predicate"), object=n.get("object"),
                polarity=int(n.get("polarity") or 0), retracted=bool(n.get("retracted")),
                provenance=[prov], confidence=rec.confidence))
        elif et == EntityType.RELATION:
            store.relations.append(RelationEdge(
                subject=(_resolve(store, n.get("subject")) or _norm(n.get("subject"))),
                predicate=(n.get("relation") or ""),
                object=(_resolve(store, n.get("object")) or _norm(n.get("object"))),
                role=_role(n.get("role")), context=(n.get("context") or {}),
                provenance=[prov], confidence=rec.confidence))

    # -- assets (figure/table dicts from ocr.pdf_extract / dispatch) --
    for a in (assets or []):
        store.assets.append(AssetNode(
            node_id=(a.get("fig_id") or a.get("table_id") or uuid.uuid4().hex),
            kind=("table" if a.get("table_id") else "figure"),
            paper_id=(a.get("paper_id") or a.get("paper") or ""),
            page=a.get("page"), bbox=a.get("bbox"), image_path=a.get("image_path"),
            caption=(a.get("caption") or ""), text=a.get("text"),
            entities=[(_resolve(store, e) or _entity_id({"name": e}, e))
                      for e in (a.get("entities") or [])],
            data_relevance=a.get("data_relevance")))

    return store
