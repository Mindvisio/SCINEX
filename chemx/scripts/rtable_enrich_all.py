import sys, json, csv, time, os
sys.path.insert(0,'/root/scinex')
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
from lib.llm_clients import call_json
from ocr.mathpix import pdf_to_markdown
from pydantic import BaseModel
from typing import Dict
PAPERS=['acsomega.2c06142','antibiotics10081002','antibiotics12071220','d2ra06667j','intechopen.108949','s13065-018-0479-1','s41598-022-21435-6']
RES='/root/scinex/chemx/results'; PDFS='/root/scinex/chemx/pdfs'
class Enrich(BaseModel):
    scaffold: str
    rgroups: Dict[str, str]
SYSTEM=("You enrich a benzimidazole SAR dataset with SMILES. Compounds in a paper share a common core scaffold and differ by one R-substituent. "
 "Given: (1) candidate core scaffolds from automated structure recognition (SMILES with dummy [*] at the variable site, noisy), (2) focused OCR text (tables+structures+prose), (3) compound ids. "
 "Identify the correct core scaffold as SMILES with EXACTLY one attachment point [*:1] (where R attaches). Then for each compound id give R as a SMILES fragment with one [*:1] attachment, read from the table and reconciled with the prose (structure-image OCR is noisy; prose authoritative). "
 "Output JSON {scaffold: <smiles [*:1]>, rgroups: {compound_id: <R smiles [*:1]>}}. R examples: methyl [*:1]C, ethyl [*:1]CC, propyl [*:1]CCC, isopropyl [*:1]C(C)C, cyclohexyl [*:1]C1CCCCC1, 2-chloroethyl [*:1]CCCl, phenyl [*:1]c1ccccc1, 4-methoxyphenyl [*:1]c1ccc(OC)cc1. Omit compounds whose R is undeterminable.")
def canon(s):
    try:
        m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else None
    except: return None
def norm_star(smi):
    m=Chem.MolFromSmiles(smi)
    if m is None: return smi
    st=[a for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(st)==1 and st[0].GetAtomMapNum()==0:
        st[0].SetAtomMapNum(1); return Chem.MolToSmiles(m)
    return smi
def enum(scaf, rs):
    scaf=norm_star(scaf); rs=norm_star(rs)
    sm=Chem.MolFromSmiles(scaf); rm=Chem.MolFromSmiles(rs)
    if sm is None or rm is None: return None
    try: return Chem.MolToSmiles(Chem.molzip(sm, rm))
    except: return None
def focus(md):
    keep=[l for l in md.split(chr(10)) if ('|' in l or '<smiles>' in l or 'ompound' in l or 'ubstituent' in l or 'erivative' in l or 'R=' in l or 'R =' in l or ' R ' in l)]
    return (chr(10).join(keep))[:16000]
def one_star(smi):
    m=Chem.MolFromSmiles(smi); return m is not None and sum(1 for a in m.GetAtoms() if a.GetAtomicNum()==0)==1
pools=json.load(open(RES+'/ocsr_pools_all.json'))
rows=list(csv.DictReader(open('/tmp/ChemX/datasets/Benzimidazoles.csv')))
import os as _os
results=json.load(open(RES+'/enrich_all.json')) if _os.path.exists(RES+'/enrich_all.json') else {}
tg=th=0
for p in PAPERS:
    if p in results and 'smiles_map' in results[p]:
        print('%-26s (cached) hit=%d/%d'%(p,results[p].get('hit',0),results[p].get('gold',0)),flush=True); continue
    t=time.time()
    mdp=RES+'/ocr_%s.md'%p
    md=open(mdp).read() if os.path.exists(mdp) else pdf_to_markdown(PDFS+'/%s.pdf'%p)
    if not os.path.exists(mdp): open(mdp,'w').write(md)
    sc=[s['smiles'] for s in pools.get(p,{}).get('scaffolds',[]) if one_star(s['smiles'])]
    bz=[s['smiles'] for s in pools.get(p,{}).get('scaffolds',[]) if s.get('bzi') and one_star(s['smiles'])]
    cand=(bz or sc)[:12]
    pred=json.load(open(RES+'/llm_%s.json'%p))
    cids=sorted(set(str(r.get('compound_id')) for r in pred if r.get('compound_id')))
    grows=[r for r in rows if r['pdf']==p and str(r.get('access')) in ('1','1.0')]
    gold={canon(r['smiles']) for r in grows}; gold.discard(None)
    prompt=('Candidate scaffolds:\n%s\n\nCompound ids: %s\n\nFocused OCR:\n%s'%(chr(10).join(cand) if cand else '(none)', ', '.join(cids), focus(md)))
    try:
        sr=call_json('deepseek-v4-pro', prompt, Enrich, system_prompt=SYSTEM, temperature=0.0, max_tokens=8000)
        en=sr.parsed
    except Exception as e:
        print('%-26s LLM_ERR %s'%(p,str(e)[:55]), flush=True); results[p]={'error':str(e)[:120]}; continue
    smap={}
    for cid, rs in en.rgroups.items():
        smi=enum(en.scaffold, rs)
        if smi: smap[cid]=smi
    es={canon(v) for v in smap.values()}; es.discard(None)
    hit=gold & es; tg+=len(gold); th+=len(hit)
    print('%-26s gold=%-3d cids=%-3d enum_hit=%d/%d %.0fs'%(p,len(gold),len(cids),len(hit),len(gold),time.time()-t), flush=True)
    results[p]={'scaffold':en.scaffold,'smiles_map':smap,'gold':len(gold),'hit':len(hit)}
    json.dump(results, open(RES+'/enrich_all.json','w'), indent=1)
json.dump(results, open(RES+'/enrich_all.json','w'), indent=1)
print('TOTAL enumerated recovery: %d/%d gold'%(th,tg))
print('ENRICH_ALL_DONE')
