"""Converge OCSR pool to ONE convention: add `engines`={molscribe,decimer,claude_vision} to each
ocsr_pool_<paper>.json. Preserves existing `pool`/`scaffolds` (parallel consumer reads scaffolds).
Gemini excluded by design. Idempotent."""
import sys, json, glob, os
sys.path.insert(0,'/root/scinex')
from chemx.smiles_router import canon
RES='/root/scinex/chemx/results'
def uniq_canon(strs):
    out=[]; seen=set()
    for s in strs:
        c=canon(s)
        if c and c not in seen: seen.add(c); out.append(c)
    return out
for uf in sorted(glob.glob('%s/ocsr_pool_*.json'%RES)):
    d=json.load(open(uf)); paper=d.get('pdf') or os.path.basename(uf)[len('ocsr_pool_'):-5]
    eng={}
    # molscribe: their top-level pool + flat molscribe_ file
    mols=[x.get('smiles') for x in d.get('pool',[]) if isinstance(x,dict) and x.get('smiles')]
    fm='%s/molscribe_%s.json'%(RES,paper)
    if os.path.exists(fm): mols+=[x for x in json.load(open(fm))]
    eng['molscribe']=[{'smiles':s} for s in uniq_canon(mols)]
    # decimer
    fd='%s/decimer_raw_%s.json'%(RES,paper)
    if os.path.exists(fd):
        eng['decimer']=[{'smiles':s} for s in uniq_canon([r.get('smiles') for r in json.load(open(fd)) if isinstance(r,dict) and r.get('smiles')])]
    # claude vision
    fc='%s/claudepg_%s.json'%(RES,paper)
    if os.path.exists(fc):
        eng['claude_vision']=[{'smiles':s} for s in uniq_canon([x.get('canon') for x in json.load(open(fc)) if isinstance(x,dict) and x.get('canon')])]
    d['engines']={k:v for k,v in eng.items() if v}
    json.dump(d, open(uf,'w'), ensure_ascii=False)
    print('%-24s engines: %s'%(paper, {k:len(v) for k,v in d['engines'].items()}))
print('CONVERGED')
