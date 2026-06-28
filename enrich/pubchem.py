"""PubChem PUG-REST resolver: compound name -> identifiers/properties + provenance URL.

Free, no API key, reachable from RU. One property call (name -> CID + formula/MW/InChI/InChIKey/
IUPAC) plus a best-effort synonyms call for the primary CAS number. SMILES is reconstructed from
the InChI via RDKit (PubChem renamed its SMILES property fields, so we do not depend on them).
Returns the normalized shape consumed by store.enrich_entities: identifiers/formats/properties/
inchikey/source_url -- or None when the name does not resolve or the service errors.
"""
from __future__ import annotations
import re
import urllib.parse
import httpx

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
_PROPS = "MolecularFormula,MolecularWeight,InChI,InChIKey,IUPACName"


def _smiles_from_inchi(inchi):
    if not inchi:
        return None
    try:
        from rdkit import Chem
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
        m = Chem.MolFromInchi(inchi)
        return Chem.MolToSmiles(m) if m is not None else None
    except Exception:
        return None


def _primary_cas(cid):
    try:
        r = httpx.get("%s/compound/cid/%s/synonyms/JSON" % (_BASE, cid),
                      timeout=30, follow_redirects=True)
        if r.status_code != 200:
            return None
        info = r.json().get("InformationList", {}).get("Information", [{}])
        for s in info[0].get("Synonym", []) if info else []:
            if _CAS.match(s):
                return s                       # first CAS-pattern synonym is the primary registry number
    except Exception:
        return None
    return None


def pubchem_lookup(name):
    """Resolve a compound name via PubChem. Returns a normalized dict or None."""
    name = (name or "").strip()
    if not name:
        return None
    q = urllib.parse.quote(name, safe="")
    try:
        r = httpx.get("%s/compound/name/%s/property/%s/JSON" % (_BASE, q, _PROPS),
                      timeout=30, follow_redirects=True)
        if r.status_code != 200:
            return None
        props = r.json().get("PropertyTable", {}).get("Properties", [])
        if not props:
            return None
        p = props[0]
    except Exception:
        return None
    cid = p.get("CID")
    inchi = p.get("InChI")
    ids, fmts, properties = {}, {}, {}
    if cid is not None:
        ids["pubchem_cid"] = str(cid)
    if p.get("MolecularFormula"):
        ids["formula"] = p["MolecularFormula"]
    cas = _primary_cas(cid) if cid is not None else None
    if cas:
        ids["cas"] = cas
    if inchi:
        fmts["inchi"] = inchi
    smiles = _smiles_from_inchi(inchi)
    if smiles:
        fmts["smiles"] = smiles
    mw = p.get("MolecularWeight")
    if mw is not None:
        try:
            properties["mw"] = float(mw)
        except (TypeError, ValueError):
            pass
    if p.get("IUPACName"):
        properties["iupac_name"] = p["IUPACName"]
    url = "https://pubchem.ncbi.nlm.nih.gov/compound/%s" % cid if cid is not None else None
    return {"name": name, "identifiers": ids, "formats": fmts, "properties": properties,
            "inchikey": p.get("InChIKey"), "source_url": url}
