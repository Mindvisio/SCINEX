"""Chemistry domain preset: molecules + reactions; RDKit validation; open-DB enrichment tools.
The core pipeline never imports RDKit — it lives here.

Compound/reaction data WITHOUT Reaxys comes from: (1) extraction from the retrieved papers
themselves, (2) cross-validation/enrichment vs OPEN DBs — PubChem + ChEMBL + ChEBI/UniChem
(compounds), Open Reaction Database + USPTO patent reactions + Rhea/KEGG (reactions). See TODO.
"""
from __future__ import annotations

from extraction.schema import ExtractedRecord, EntityType, ValidationStatus
from domains.base import DomainPreset, register

try:
    from rdkit import Chem
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")
    _HAS_RDKIT = True
except Exception:
    _HAS_RDKIT = False


def _canon(smiles: str):
    if not _HAS_RDKIT:
        return None
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    return Chem.MolToSmiles(m), Chem.MolToInchiKey(m)


def name_to_smiles(name: str):
    """IUPAC/trivial chemical name -> {smiles, inchikey, name, source} via OPSIN (deterministic)
    + RDKit canon, or None. The graph entity-in-text arbiter: a free name->structure check (no LLM)."""
    if not name or not name.strip():
        return None
    try:
        from py2opsin import py2opsin
    except Exception:
        return None
    raw = (py2opsin(name.strip()) or "").strip().splitlines()
    smi = raw[0].strip() if raw else ""
    if not smi:
        return None
    res = _canon(smi)
    if res is None:
        return None
    canon, ikey = res
    return {"smiles": canon, "inchikey": ikey, "name": name.strip(), "source": "opsin"}


def validate_molecule(rec: ExtractedRecord) -> ExtractedRecord:
    """RDKit: SMILES -> canonical SMILES + InChIKey. Canonicalization settles structural identity
    and stereochemistry; the InChIKey skeleton is tautomer-insensitive. Isomer/homolog
    *relationships* across the corpus are an analytics step, not this validator; biological
    (sequence) homology is bioinformatics (alignment/orthology), not RDKit.
    """
    ids = rec.normalized.setdefault("identifiers", {})
    smi = ids.get("smiles") or rec.normalized.get("smiles")
    opsin_used = False
    if not smi:
        # OPSIN enrichment (graph E): derive structure from the name deterministically
        name = rec.normalized.get("name") or rec.value
        hit = name_to_smiles(name) if name else None
        if hit:
            smi = hit["smiles"]
            ids["smiles"] = smi
            ids.setdefault("inchikey", hit["inchikey"])
            opsin_used = True
    if not smi:
        rec.validation = ValidationStatus.UNVERIFIED
        rec.validation_detail = "no smiles or resolvable name"
        return rec
    res = _canon(smi)
    if res is None:
        rec.validation = ValidationStatus.UNVERIFIED if not _HAS_RDKIT else ValidationStatus.FAILED
        rec.validation_detail = "rdkit unavailable" if not _HAS_RDKIT else "unparseable SMILES"
        return rec
    canon, ikey = res
    ids["smiles"] = canon
    ids.setdefault("inchikey", ikey)
    rec.validation = ValidationStatus.PASSED
    rec.validation_detail = "rdkit canonical" + (" via opsin(name)" if opsin_used else "")
    rec.confidence = max(rec.confidence, 0.8)
    # TODO open-data tools (the Reaxys substitute):
    #   pubchem_lookup(name|inchikey)->CID+props (PUG REST); chembl_lookup(inchikey)->bioactivity;
    #   unichem xrefs; reactions: Open Reaction Database + USPTO(Lowe) + Rhea/KEGG (biochemical).
    return rec


CHEMISTRY = register(DomainPreset(
    name="chemistry",
    description="Computational/medicinal chemistry: molecules, reactions, DFT/MD methods, properties.",
    focus_types=[EntityType.ENTITY, EntityType.RELATION, EntityType.METHOD, EntityType.MEASUREMENT],
    entity_kinds=["molecule", "reaction", "target", "material"],
    id_schemes=["smiles", "inchi", "inchikey", "formula", "cas", "pubchem_cid", "chembl",
                "drugbank", "reaction_smiles", "rinchi", "pdb", "cif"],
    extract_hint=("Molecules: entity type=molecule, put SMILES/InChIKey in identifiers. "
                  "Reactions: entity type=reaction (reaction_smiles if inferable); emit ONE relation "
                  "per participant with role (reactant/product/catalyst/solvent/reagent). Methods: "
                  "method.params with software/method_family/functional/basis_set/forcefield/md_engine. "
                  "Properties: measurement with value+unit AND analyte=the measured compound/material."),
    validators={"molecule": validate_molecule},
))


_STRUCT_KW = ("structure", "compound", "scheme", "synthesi", "molecul",
              "derivativ", "skeletal", "reaction")


def _looks_structural(caption: str) -> bool:
    c = (caption or "").lower()
    return any(k in c for k in _STRUCT_KW)


def molecules_from_figures(figures, paper, *, engines=("vision", "decimer"),
                           gate_caption=True):
    """OCSR (graph C): figure crops -> molecule ExtractedRecords. `figures` = dicts with image_path
    + caption (from ocr.pdf_extract). gate_caption keyword-filters structural figures. DECIMER runs
    ONCE over all selected crops (batch). OCSR status -> validation: ok=PASSED,
    review/disagree=UNVERIFIED(+detail), failed dropped."""
    from ocr.ocsr import images_to_smiles

    def _keep(f):
        if not f.get("image_path"):
            return False
        if gate_caption and not _looks_structural(f.get("caption") or ""):
            return False
        return True

    sel = [f for f in (figures or []) if _keep(f)]
    if not sel:
        return []
    mols = images_to_smiles([f["image_path"] for f in sel], engines=engines)   # one DECIMER load
    out = []
    for fig in sel:
        mol = mols.get(fig["image_path"])
        if not mol or mol.status == "failed" or not mol.inchikey:
            continue
        cap = fig.get("caption") or ""
        out.append(ExtractedRecord(
            paper=paper,
            entity_type=EntityType.ENTITY,
            value=(cap[:120] or "structure"),
            normalized={"type": "molecule", "name": (cap[:120] or None),
                        "identifiers": {"smiles": mol.smiles, "inchikey": mol.inchikey},
                        "formats": {"smiles": mol.smiles}, "source": "ocsr",
                        "ocsr_backend": mol.backend, "ocsr_status": mol.status,
                        "figure": fig.get("fig_id") or fig.get("page")},
            span=None,
            extractor=f"ocsr:{mol.backend}",
            confidence=mol.confidence or 0.5,
            validation=ValidationStatus.PASSED if mol.status == "ok" else ValidationStatus.UNVERIFIED,
            validation_detail=f"ocsr {mol.status}",
        ))
    return out
