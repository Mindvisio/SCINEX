"""Validation / processing report (slide 32). Pure counting over the final record set;
emits a Markdown block (for the README) and a stats dict (for programmatic checks).
"""
from __future__ import annotations
from collections import Counter


def _uniq_compounds(records) -> int:
    keys = set()
    for r in records:
        k = r.inchikey or (r.pubchem_cid and "cid:" + str(r.pubchem_cid)) or \
            (r.cas and "cas:" + r.cas) or (r.name_std and "nm:" + r.name_std.lower())
        if k:
            keys.add(k)
    return len(keys)


def build_report(records) -> tuple:
    n = len(records)
    primaries = [r for r in records if r.is_primary is not False]
    val = Counter(r.validation for r in records)
    src = Counter(r.source_type for r in records)
    extr = Counter((r.extractor or "?").split(":")[0] for r in records)
    dup_groups = len({r.dup_group for r in records if r.dup_group})
    conf_groups = len({r.conflict_group for r in records if r.conflict_group})
    removed = sum(1 for r in records if r.is_primary is False)

    issues = Counter()
    for r in records:
        d = (r.validation_detail or "").lower()
        rv = (r.review_reason or "").lower()
        if "unparseable smiles" in d or "malformed smiles" in rv:
            issues["malformed SMILES"] += 1
        if "unresolved name" in rv or "name did not resolve" in d:
            issues["unresolved compound name"] += 1
        if "unit missing" in rv or "unit assumed" in rv:
            issues["missing unit"] += 1
        if "invalid unit" in rv:
            issues["invalid unit"] += 1
        if "unparseable value" in rv:
            issues["unparseable value"] += 1
        if r.conflict_flag:
            issues["conflicting value"] += 1
        if "range" in rv:
            issues["value reported as range"] += 1
        if "implausible" in rv:
            issues["implausible value (out of range)"] += 1
        if "weak " in rv:
            issues["weak/inactive value (>1 mM)"] += 1
        if "suspicious range" in rv:
            issues["suspicious range (descending/too wide)"] += 1

    per_pdf = Counter(r.source_pdf for r in records)
    stats = {
        "raw_records": n, "final_records_dedup": len(primaries),
        "duplicates_tagged": removed, "dup_groups": dup_groups,
        "conflict_groups": conf_groups,
        "needs_review": sum(1 for r in records if r.needs_review),
        "validation": dict(val), "by_source_type": dict(src), "by_extractor": dict(extr),
        "unique_compounds": _uniq_compounds(records),
        "structures_recognized": sum(1 for r in records if r.inchikey),
        "pdfs": len(per_pdf),
    }

    L = []
    L.append("## Processing report\n")
    L.append("| metric | value |")
    L.append("|---|---|")
    L.append("| PDFs processed | %d |" % len(per_pdf))
    L.append("| Raw records | %d |" % n)
    L.append("| Final records (deduplicated view) | %d |" % len(primaries))
    L.append("| Duplicate rows tagged | %d |" % removed)
    L.append("| Dedup groups | %d |" % dup_groups)
    L.append("| Conflict groups | %d |" % conf_groups)
    L.append("| Records needing manual review | %d |" % stats["needs_review"])
    L.append("| Unique compounds | %d |" % stats["unique_compounds"])
    L.append("| Structures recognised (InChIKey) | %d |" % stats["structures_recognized"])
    L.append("\n**Validation:** " + ", ".join("%s %d" % (k, v) for k, v in sorted(val.items())))
    L.append("\n**By source type:** " + ", ".join("%s %d" % (k, v) for k, v in sorted(src.items())))
    L.append("\n**By extractor:** " + ", ".join("%s %d" % (k, v) for k, v in sorted(extr.items())))
    if issues:
        L.append("\n**Top validation issues:**")
        for k, v in issues.most_common():
            L.append("- %s: %d" % (k, v))
    if per_pdf:
        L.append("\n**Records per PDF:**")
        for k, v in per_pdf.most_common():
            L.append("- %s: %d" % (k, v))
    return "\n".join(L) + "\n", stats