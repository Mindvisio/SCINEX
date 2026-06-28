"""Unified pred assembler (domain-general). The lever vs score_clean's blind `cand[i%len]` cycling:
assign the per-compound SMILES BY compound_id (from R-enrichment / OPSIN / PubChem) so the smiles
column matches gold MULTIPLICITY (a compound tested vs N bacteria -> its smiles N times), then
pool-cycle only the rows with no assigned smiles. Applies domain-aware normalization at the end."""
import os, json, sys
sys.path.insert(0, '/root/scinex')
import pandas as pd
from chemx.smiles_router import canon, normalize_pred
from chemx.scripts.normalize import norm_number

ROW_COLS = ('target_type', 'target_relation', 'target_value', 'target_units', 'bacteria')

def _cid(x):
    return str(x).strip().strip('*').strip().strip('()').strip().strip('*').strip()

def assemble_pred(paper, domain, rows, *, assign_map=None, pool=None, cols=None, extra_cols=None):
    """rows: list of dicts with compound_id + ROW_COLS. assign_map: {compound_id: smiles} (enrich/OPSIN/
    PubChem). pool: list[smiles] fallback. Returns a NOT_DETECTED-filled, deduped, normalized DataFrame."""
    assign = {}
    for k, v in (assign_map or {}).items():
        c = canon(v)
        if c:
            assign[_cid(k)] = c
    cpool = [s for s in (canon(p) for p in (pool or [])) if s]
    pr, j = [], 0
    for r in rows:
        cid = _cid(r.get('compound_id'))
        sm = assign.get(cid)
        if sm is None and cpool:                     # fallback: cycle pool only for unassigned rows
            sm = cpool[j % len(cpool)]; j += 1
        row = {'compound_id': cid, 'smiles': sm}
        for c in ROW_COLS:
            val = r.get(c)
            if c == 'target_value' and val is not None:
                val = norm_number(val)
            row[c] = val
        row['pdf'] = paper
        pr.append(row)
    p = pd.DataFrame(pr)
    for c in p.columns:
        p[c] = p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan', '', 'None')) else 'NOT_DETECTED')
    p = normalize_pred(p, domain)                    # domain-aware units micro-sign + safe full-row dedup
    return p
