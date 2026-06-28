"""Deduplication + record linkage (slides 17-20).

Levels (slide 17):
  L1 identical observation        L2 same canonical compound id
  L3 same compound + property     L4 same experiment (compound+property+value+target)
  L5 derived/copied across DBs  <- NOT decidable from PDFs alone; left for provenance review.

Structure-aware: the canonical key is the InChIKey (then PubChem CID, then CAS). Compounds that
never resolved to a structure are linked by fuzzy name match (RapidFuzz, slide 19). Nothing is
deleted here — rows are tagged (dup_group/dup_level/is_primary); the deduplicated VIEW keeps primaries.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional

from rapidfuzz import fuzz

_VAL_ORDER = {"passed": 0, "unverified": 1, "failed": 2}
_NAME_FUZZ = 92


def _entity_id(rec) -> Optional[str]:
    if rec.inchikey:
        return "ik:" + rec.inchikey
    if rec.pubchem_cid:
        return "cid:" + str(rec.pubchem_cid)
    if rec.cas:
        return "cas:" + rec.cas
    return None


def _fuzzy_name_ids(records) -> dict:
    """id(record)->synthetic 'nm:N' cluster id, for structure-less records, via name similarity."""
    reps: list = []                                   # (cluster_id, representative_name)
    out = {}
    for rec in records:
        if _entity_id(rec) is not None or not rec.name_std:
            continue
        s = rec.name_std.lower()
        match = None
        for cid, rep in reps:
            if fuzz.WRatio(s, rep) >= _NAME_FUZZ:
                match = cid
                break
        if match is None:
            match = "nm:%d" % len(reps)
            reps.append((match, s))
        out[id(rec)] = match
    return out


def _value_bucket(rec):
    if rec.value_std is None:
        return None
    return round(rec.value_std, 4)


def _primary(group):
    """best validation -> most identifiers -> earliest extracted."""
    def score(r):
        ids = sum(x is not None for x in (r.inchikey, r.pubchem_cid, r.cas, r.smiles_canonical))
        return (_VAL_ORDER.get(r.validation, 3), -ids, r.extracted_at)
    return min(group, key=score)


def _level(group) -> int:
    obs = lambda r: (r.source_pdf, r.source_type, r.name_raw, r.smiles_raw, r.value_raw, r.unit_raw, r.target_raw)
    if len({obs(r) for r in group}) == 1:
        return 1
    has_prop = all(r.property for r in group)
    if has_prop and len({_value_bucket(r) for r in group}) == 1:
        return 4
    if has_prop:
        return 3
    return 2


def deduplicate(records) -> None:
    """Tag records in place with dup_group / dup_level / is_primary."""
    fuzzy = _fuzzy_name_ids(records)
    groups = defaultdict(list)
    for rec in records:
        eid = _entity_id(rec) or fuzzy.get(id(rec))
        if eid is None:                               # un-anchored row: stands alone
            rec.is_primary = True
            continue
        groups[(eid, rec.property, _value_bucket(rec), rec.unit_std)].append(rec)
    gi = 0
    for key, members in groups.items():
        if len(members) == 1:
            members[0].is_primary = True
            continue
        gi += 1
        gid = "dup_%03d" % gi
        lvl = _level(members)
        prim = _primary(members)
        for r in members:
            r.dup_group = gid
            r.dup_level = lvl
            r.is_primary = (r is prim)