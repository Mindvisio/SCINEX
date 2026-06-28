"""Identifier resolution + structural validation (slides 9-16, 24).

Deterministic chain per record:
  1. SMILES present        -> RDKit canonical SMILES + InChIKey   (validation = passed/failed)
  2. else name present     -> OPSIN name->structure (rule-based) -> RDKit canon
  3. cross-identifier fill -> PubChem PUG-REST by name OR by InChIKey -> CID/CAS/formula/MW/IUPAC
Names that resolve to nothing (trade names, ambiguous abbreviations, 'compound 7b' - slide 16)
are left UNVERIFIED and pushed to the human-review queue, never invented.

Compound cells in med-chem tables are often 'LABEL (trivial name)', e.g. '15a (levorphanol)';
_name_candidates() unwraps the trivial name so it can resolve, while bare labels ('7b') do not.

Self-contained name->structure (OPSIN+RDKit) here; cross-id enrichment reuses enrich.pubchem.
"""
from __future__ import annotations
import re
import time
import urllib.parse
from typing import Optional

import httpx

from enrich.pubchem import pubchem_lookup               # PubChem by name (reused scinex brick)

_PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_GAP = 0.20                                     # polite spacing (PUG-REST ~5 req/s)
_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
_LABEL = re.compile(r"^(?:compound|cmpd|cpd|entry)?\s*\d{1,4}[a-z]?$|^[A-Za-z]\d{0,3}$", re.I)
_NAME_STOP = {"compound", "compd", "cmpd", "cpd", "entry", "table", "ligand", "analog",
              "analogue", "derivative", "control", "vehicle", "reference", "standard",
              "title", "scheme", "figure", "example", "inhibitor", "agonist", "antagonist"}


def _is_label(name):
    """True for compound LABELS ('7b', '12', 'compound 3', 'A1') that must NOT be name-resolved:
    PubChem name search returns spurious hits for such tokens (slide 16 - manual cross-ref needed)."""
    s = (name or "").strip()
    return len(s) <= 2 or bool(_LABEL.match(s))


def _name_candidates(name):
    """Resolution-name variants for a raw compound cell. 'LABEL (trivial)' -> trivial; code-prefixed
    name -> stripped. Pure labels / stop-words / numbers -> excluded. Returns ordered, de-duped."""
    name = (name or "").strip()
    if not name:
        return []
    cands = [name]
    m = re.search(r"\(([^)]{3,})\)", name)                # parenthetical trivial name
    if m:
        cands.append(m.group(1).strip())
    base = re.sub(r"\s*\([^)]*\)", "", name).strip()       # name minus parenthetical
    if base and base != name:
        cands.append(base)
    m2 = re.match(r"^\d{1,4}[a-z]?[\s\-]+(.{3,})$", name)   # '15a levorphanol' / '15a-levorphanol'
    if m2:
        cands.append(m2.group(1).strip())
    out = []
    for c in cands:
        c = c.strip(" ,;:")
        if (c and c not in out and not _is_label(c) and not c.isdigit()
                and c.lower() not in _NAME_STOP and len(c) >= 3):
            out.append(c)
    return out


def _rdkit():
    from rdkit import Chem
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")
    return Chem


def canon_smiles(smiles: Optional[str]):
    """SMILES -> (canonical_smiles, inchikey) or None (unparseable). RDKit is the arbiter."""
    if not smiles:
        return None
    try:
        Chem = _rdkit()
    except Exception:
        return None
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    return Chem.MolToSmiles(m), Chem.MolToInchiKey(m)


def _name_to_smiles(name):
    """Systematic/IUPAC name -> {smiles, inchikey} via OPSIN (deterministic) + RDKit canon, or None."""
    if not name or not name.strip():
        return None
    try:
        from py2opsin import py2opsin
    except Exception:
        return None
    raw = (py2opsin(name.strip()) or "")
    raw = raw if isinstance(raw, str) else (raw[0] if raw else "")
    smi = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if not smi:
        return None
    res = canon_smiles(smi)
    return {"smiles": res[0], "inchikey": res[1]} if res else None


def _pubchem_by_inchikey(ikey: str):
    """InChIKey -> normalised PubChem dict (CID/CAS/formula/MW/IUPAC) or None."""
    if not ikey or not _INCHIKEY.match(ikey):
        return None
    props = "MolecularFormula,MolecularWeight,InChI,InChIKey,IUPACName"
    try:
        r = httpx.get("%s/compound/inchikey/%s/property/%s/JSON" % (_PUBCHEM, ikey, props),
                      timeout=30, follow_redirects=True)
        if r.status_code != 200:
            return None
        rows = r.json().get("PropertyTable", {}).get("Properties", [])
        if not rows:
            return None
        p = rows[0]
    except Exception:
        return None
    cid = p.get("CID")
    cas = None
    if cid is not None:
        try:
            time.sleep(_PUBCHEM_GAP)
            s = httpx.get("%s/compound/cid/%s/synonyms/JSON" % (_PUBCHEM, cid), timeout=30,
                          follow_redirects=True)
            if s.status_code == 200:
                syn = s.json().get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
                cas = next((x for x in syn if _CAS.match(x)), None)
        except Exception:
            pass
    return {"pubchem_cid": str(cid) if cid is not None else None, "cas": cas,
            "formula": p.get("MolecularFormula"),
            "mw": _f(p.get("MolecularWeight")), "iupac_name": p.get("IUPACName")}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class Resolver:
    """Stateful resolver with an in-memory cache (reproducible + polite to PubChem)."""

    def __init__(self, enrich: bool = True):
        self.enrich = enrich
        self._name_cache: dict = {}
        self._ikey_cache: dict = {}

    def _pubchem_name(self, name):
        if name not in self._name_cache:
            time.sleep(_PUBCHEM_GAP)
            self._name_cache[name] = pubchem_lookup(name)
        return self._name_cache[name]

    def _pubchem_ikey(self, ikey):
        if ikey not in self._ikey_cache:
            self._ikey_cache[ikey] = _pubchem_by_inchikey(ikey)
        return self._ikey_cache[ikey]

    def resolve(self, rec) -> None:
        """Fill structure + identifiers + validation on a Record in place."""
        # 1) structure from SMILES
        if rec.smiles_raw:
            res = canon_smiles(rec.smiles_raw)
            if res:
                rec.smiles_canonical, rec.inchikey = res
                rec.validation, rec.validation_detail = "passed", "rdkit canonical"
            else:
                rec.validation, rec.validation_detail = "failed", "unparseable SMILES"
                rec.flag_review("malformed SMILES")
        # 2) structure from name via OPSIN (try parenthetical / trivial-name variants)
        if not rec.smiles_canonical and rec.name_raw:
            for cand in _name_candidates(rec.name_raw):
                hit = _name_to_smiles(cand)
                if hit:
                    rec.smiles_canonical = hit["smiles"]
                    rec.inchikey = rec.inchikey or hit["inchikey"]
                    rec.name_std = cand
                    rec.validation, rec.validation_detail = "passed", "opsin name->structure"
                    break
        # 3) cross-identifier enrichment (PubChem)
        if self.enrich:
            info = None
            if rec.inchikey:
                info = self._pubchem_ikey(rec.inchikey)
            if not info and rec.name_raw and not rec.smiles_canonical:
                for cand in _name_candidates(rec.name_raw):
                    pc = self._pubchem_name(cand)
                    if not pc:
                        continue
                    rec.name_std = rec.name_std or cand
                    rec.inchikey = rec.inchikey or pc.get("inchikey")
                    rec.smiles_canonical = rec.smiles_canonical or pc.get("formats", {}).get("smiles")
                    ids, props = pc.get("identifiers", {}), pc.get("properties", {})
                    info = {"pubchem_cid": ids.get("pubchem_cid"), "cas": ids.get("cas"),
                            "formula": ids.get("formula"), "mw": props.get("mw"),
                            "iupac_name": props.get("iupac_name")}
                    if rec.smiles_canonical and rec.validation != "passed":
                        rec.validation, rec.validation_detail = "passed", "pubchem name resolution"
                    break
            if info:
                rec.pubchem_cid = rec.pubchem_cid or info.get("pubchem_cid")
                rec.cas = rec.cas or info.get("cas")
                rec.formula = rec.formula or info.get("formula")
                rec.mw = rec.mw or info.get("mw")
                rec.iupac_name = rec.iupac_name or info.get("iupac_name")
        # 4) unresolved entity -> review (slide 16)
        if rec.name_raw and not rec.smiles_canonical and not rec.pubchem_cid:
            if rec.validation == "unverified":
                rec.validation_detail = rec.validation_detail or "name did not resolve"
            if _is_label(rec.name_raw):
                rec.flag_review("compound label '%s' (needs cross-reference to a structure)" % rec.name_raw.strip())
            else:
                rec.flag_review("unresolved name (trade name / abbreviation?)")
        if rec.name_std is None and rec.name_raw:
            rec.name_std = rec.name_raw.strip()