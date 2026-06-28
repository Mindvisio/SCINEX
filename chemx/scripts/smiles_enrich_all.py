import sys, json, os, re
sys.path.insert(0,'/root/scinex')
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
from lib.llm_clients import call_json
from pydantic import BaseModel
from typing import Dict

class RMap(BaseModel):
    rgroups: Dict[str, str]

SYSTEM=("You read a benzimidazole SAR paper where numbered compounds share ONE common scaffold and differ only by a substituent R at the [*:1] attachment point. "
  "Given the scaffold, OCR text/tables (Mathpix renders some R groups inline as <smiles> with placeholder atoms like [Y],[Te]) and prose, output for each compound id the substituent R as a SMILES fragment with EXACTLY one attachment point [*:1]. "
  "Reconcile noisy OCR using prose. Examples: methyl [*:1]C ; ethyl [*:1]CC ; propyl [*:1]CCC ; isopropyl [*:1]C(C)C ; cyclohexyl [*:1]C1CCCCC1 ; 2-chloroethyl [*:1]CCCl ; 2-chlorophenyl [*:1]c1ccccc1Cl ; 4-methoxyphenyl [*:1]c1ccc(OC)cc1 . Output JSON {\"rgroups\": {compound_id: R_fragment}}.")

def focus(md, limit=20000):
    keep=[ln for ln in md.split(chr(10)) if ('<smiles>' in ln or '|' in ln or re.search(r'\bR\s*[=:]|substituent|scaffold|scheme|compound\s+\d|derivative|propyl|methyl|phenyl|cyclo', ln, re.I))]
    return (chr(10).join(keep))[:limit]
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else None
    except: return None
def label_scaffold(smi):
    m=Chem.MolFromSmiles(smi)
    if m is None: return None,0
    d=[a for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(d)!=1: return None,len(d)
    d[0].SetAtomMapNum(1); return m,1

papers=['acsomega.2c06142','antibiotics10081002','antibiotics12071220','d2ra06667j','intechopen.108949','s13065-018-0479-1','s41598-022-21435-6']
RES='/root/scinex/chemx/results'
for p in papers:
    try:
        pred=json.load(open('%s/llm_%s.json'%(RES,p)))
        cids=sorted(set(x.get('compound_id') for x in pred if x.get('compound_id')))
        pool=json.load(open('%s/ocsr_pool_%s.json'%(RES,p)))
        scafs=[x['smiles'] for x in pool.get('scaffolds',[])]
        scaf_mol=scaf_smi=None
        for s in scafs:
            mm,nd=label_scaffold(s)
            if mm is not None: scaf_mol,scaf_smi=mm,s; break
        if scaf_mol is None:
            print('%-26s NO_SINGLE_DUMMY_SCAFFOLD scafs=%d'%(p,len(scafs)), flush=True); continue
        md=open('%s/ocr_%s.md'%(RES,p)).read()
        prompt=('Scaffold (R at [*:1]): %s\n\nCompound IDs: %s\n\nOCR text/tables:\n%s\n\nReturn R fragment for every compound id.'%(scaf_smi,cids,focus(md)))
        sr=call_json('deepseek-v4-pro', prompt, RMap, system_prompt=SYSTEM, temperature=0.0, max_tokens=6000)
        out={}
        for cid,r in sr.parsed.rgroups.items():
            rm=Chem.MolFromSmiles(r)
            if rm is None: continue
            try: out[cid]=Chem.MolToSmiles(Chem.molzip(scaf_mol,rm))
            except Exception: pass
        json.dump(out, open('%s/smiles_enriched_%s.json'%(RES,p),'w'), indent=1)
        print('%-26s cids=%-3d enriched=%-3d %.0fs'%(p,len(cids),len(out),sr.latency_s), flush=True)
    except Exception as e:
        print('%-26s ERROR %s'%(p,str(e)[:90]), flush=True)
print('ENRICH_DONE', flush=True)
