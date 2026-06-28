"""Conflict detection (slides 21-23).

A conflict = records about the SAME compound + SAME property whose standardised values disagree
beyond a family tolerance. Per the lecture, conflicts must become METADATA, not be averaged or
silently dropped: every conflicting value is kept and tagged with a shared conflict_group.

Tolerances (relative unless noted): concentration/mass-conc/MW = 2x; temperature = +-5 degC abs;
percent = +-10 abs. These are deliberately loose — assay variability is large; only real
disagreement is flagged.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional

_REL_UNITS = {"nM", "g/L", "g/mol"}


def _entity_id(rec) -> Optional[str]:
    if rec.inchikey:
        return "ik:" + rec.inchikey
    if rec.pubchem_cid:
        return "cid:" + str(rec.pubchem_cid)
    if rec.cas:
        return "cas:" + rec.cas
    if rec.name_std:
        return "nm:" + rec.name_std.lower()
    return None


def _disagree(values, unit) -> bool:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return False
    lo, hi = min(vals), max(vals)
    if unit == "degC":
        return (hi - lo) > 5.0
    if unit == "%":
        return (hi - lo) > 10.0
    if unit in _REL_UNITS:
        return lo <= 0 or (hi / lo) > 2.0
    return lo <= 0 or (hi / lo) > 2.0                 # default: relative 2x


def detect_conflicts(records) -> None:
    """Tag records in place with conflict_group / conflict_flag. Considers PRIMARY rows only
    (post-dedup) so duplicate measurements don't masquerade as conflicts."""
    buckets = defaultdict(list)
    for rec in records:
        if rec.is_primary is False:
            continue
        if not rec.property or rec.value_std is None:
            continue
        eid = _entity_id(rec)
        if eid is None:
            continue
        buckets[(eid, rec.property, rec.unit_std)].append(rec)
    ci = 0
    for (eid, prop, unit), members in buckets.items():
        if len(members) < 2:
            continue
        if _disagree([m.value_std for m in members], unit):
            ci += 1
            cid = "conf_%03d" % ci
            for m in members:
                m.conflict_group = cid
                m.conflict_flag = True
                m.flag_review("value conflict on %s (kept as metadata, not averaged)" % prop)