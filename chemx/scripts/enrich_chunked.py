import sys, json, os, re
sys.path.insert(0,'/root/scinex')
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
from lib.llm_clients import call_json
from pydantic import BaseModel
from typing import Dict
class RMap(BaseModel):
    rgroups: Dict[str,str]
SYSTEM=("You read a benzimidazole SAR paper where numbered compounds share ONE scaffold and differ only by a substituent R at the [*:1] attachment point. "
  "Given the scaffold, OCR text/tables (Mathpix renders some R groups inline as <smiles> with placeholder atoms like [Y],[Te]) and prose, output for EACH listed compound id its R as a SMILES fragment with EXACTLY one attachment point [*:1]. "
  "Reconcile noisy OCR via prose. Examples: methyl [*:1]C ; ethyl [*:1]CC ; propyl [*:1]CCC ; isopropyl [*:1]C(C)C ; cyclohexyl [*:1]C1CCCCC1 ; 2-chloroethyl [*:1]CCCl ; 2-chlorophenyl [*:1]c1ccccc1Cl ; 4-methoxyphenyl [*:1]c1ccc(OC)cc1 . If a compound's R cannot be determined, omit it. Output JSON {\"rgroups\": {compound_id: R_fragment}}.")
def focus(md, limit=14000):
    keep=[ln for ln in md.split(chr(10)) if ('<smiles>' in ln or '|' in ln or re.search(r'\bR\s*[=:]|substituent|scheme|compound\s+\d|derivative|propyl|methyl|phenyl|cyclo|ethyl', ln, re.I))]
    return (chr(10).join(keep))[:limit]
def label(smi):
    m=Chem.MolFromSmiles(smi)
    if m is None: return None
    d=[a for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(d)!=1: return None
    d[0].SetAtomMapNum(1); return m
def chunks(l,n):
    for i in range(0,len(l),n): yield l[i:i+n]
papers=['acsomega.2c06142','antibiotics10081002','d2ra06667j','intechopen.108949','s13065-018-0479-1','s41598-022-21435-6']
RES='/root/scinex/chemx/results'
for p in papers:
    try:
        sc=json.load(open('%s/scaffold_%s.json'%(RES,p))).get('scaffold')
        scaf=label(sc) if sc else None
        if scaf is None: print('%-26s NO_USABLE_SCAFFOLD'%p, flush=True); continue
        rows=json.load(open('/tmp/chemx_benz/llm_%s.json'%p))
        cids=sorted(set(str(r['compound_id']) for r in rows))
        foc=focus(open('%s/ocr_%s.md'%(RES,p)).read())
        out={}
        for batch in chunks(cids,18):
            prompt=('Scaffold (R at [*:1]): %s\n\nCompound IDs: %s\n\nOCR text/tables:\n%s\n\nReturn R fragment for each listed compound id.'%(sc,batch,foc))
            for model in ['claude-opus','deepseek-direct']:
                try:
                    sr=call_json(model, prompt, RMap, system_prompt=SYSTEM, temperature=0.0, max_tokens=4000)
                    for cid,r in sr.parsed.rgroups.items():
                        rm=Chem.MolFromSmiles(r)
                        if rm is None: continue
                        try: out[cid]=Chem.MolToSmiles(Chem.molzip(scaf,rm))
                        except Exception: pass
                    break
                except Exception: continue
        json.dump(out, open('%s/enriched_%s.json'%(RES,p),'w'), indent=1)
        print('%-26s cids=%-3d enriched=%-3d'%(p,len(cids),len(out)), flush=True)
    except Exception as e:
        print('%-26s ERROR %s'%(p,str(e)[:80]), flush=True)
print('ENRICH2_DONE', flush=True)
