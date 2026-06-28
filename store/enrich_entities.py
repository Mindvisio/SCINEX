"""Entity enrichment: molecule nodes -> external-DB identifiers/properties + provenance, with
InChIKey cross-validation. Pluggable sources (adapters in enrich/): NIST now; PubChem/ChEMBL later.

Per molecule node: resolve by name (label/names) against each source; ACCEPT a hit only if the
source InChIKey skeleton (first block) matches ours -- a name that resolves to a different compound
is skipped and counted (no silent pollution). On a confirmed hit: merge cas/formula into
identifiers, inchi into formats (without overwriting our canonical one), mw into properties, and
append an external Provenance carrying source_url. Network; opt-in pass (build_corpus --enrich-db).
Cross-validation is the point: NIST InChIKey == our RDKit InChIKey is independent confirmation.
"""
from __future__ import annotations
from extraction.schema import ValidationStatus
from store.schema import Provenance


def _skeleton(ikey):
    return (ikey or "").split("-")[0].upper()


def _nist_resolver(name):
    """name -> normalized enrichment dict | None (adapter over enrich.nist.nist_lookup)."""
    from enrich.nist import nist_lookup
    r = nist_lookup(name)
    if not r:
        return None
    ids, fmts, props = {}, {}, {}
    if r.get("cas_number"):
        ids["cas"] = r["cas_number"]
    if r.get("formula"):
        ids["formula"] = r["formula"]
    if r.get("inchi"):
        fmts["inchi"] = r["inchi"]
    if r.get("mw") is not None:
        props["mw"] = r["mw"]
    return {"identifiers": ids, "formats": fmts, "properties": props,
            "inchikey": r.get("inchikey"), "source_url": r.get("source_url")}


def _pubchem_resolver(name):
    """name -> normalized enrichment dict | None (adapter over enrich.pubchem.pubchem_lookup).
    PubChem already returns our normalized shape, so this is a thin pass-through."""
    from enrich.pubchem import pubchem_lookup
    return pubchem_lookup(name)


SOURCE_TAGS = {"nist": "webbook", "pubchem": "pug-rest"}
RESOLVERS = {"nist": _nist_resolver, "pubchem": _pubchem_resolver}


def enrich_entities(store, *, sources=("pubchem", "nist"), max_lookups=None) -> dict:
    """Enrich molecule nodes in place from external DBs (InChIKey-cross-validated). Returns a summary."""
    mols = [e for e in store.entities.values() if e.kind == "molecule"]
    cache: dict = {}
    enriched = confirmed = mismatched = 0
    n = 0
    for node in mols:
        if any((p.extractor or "").split(":")[0] in sources for p in node.provenance):
            continue                                   # idempotent: a prior DB pass already stamped it
        our_sk = _skeleton(node.identifiers.get("inchikey"))
        names = [x for x in ([node.label] + list(node.names)) if x and len(x) >= 2]
        for src in sources:
            if max_lookups is not None and n >= max_lookups:
                break
            res = None
            for nm in dict.fromkeys(names):             # dedup, keep order
                key = (src, nm.lower())
                if key not in cache:
                    n += 1
                    try:
                        cache[key] = RESOLVERS[src](nm)
                    except Exception:
                        cache[key] = None
                res = cache[key]
                if res:
                    break
            if not res:
                continue
            src_sk = _skeleton(res.get("inchikey"))
            if our_sk and src_sk and our_sk != src_sk:
                mismatched += 1                        # name -> different compound; do not trust
                continue
            node.identifiers.update(res["identifiers"])
            for k, v in res["formats"].items():
                node.formats.setdefault(k, v)          # keep our canonical inchi if present
            node.properties.update(res["properties"])
            node.provenance.append(Provenance(
                paper_id="", extractor=f"{src}:{SOURCE_TAGS.get(src, src)}", source_url=res.get("source_url"),
                confidence=0.9 if our_sk else 0.6,
                validation=ValidationStatus.PASSED if our_sk else ValidationStatus.UNVERIFIED))
            enriched += 1
            if our_sk:
                confirmed += 1
            break                                      # first confirming source wins (MVP)
    return {"molecules": len(mols), "enriched": enriched, "confirmed": confirmed,
            "mismatched": mismatched, "lookups": n}
