import sys, glob, json, time
sys.path.insert(0,'/root/scinex')
from lib.llm_clients import call_vision
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
def canon(s):
    try: m=Chem.MolFromSmiles(str(s).strip()); return Chem.MolToSmiles(m) if m else None
    except: return None
SYS='Expert OCSR. Identify EVERY distinct chemical structure on these pages (expand R-table/Markush per labelled variant). Output ONLY a JSON array of {"label":"","smiles":""}. No prose, no fences.'
pages=sorted(glob.glob('/tmp/acsomegapg/*.png')); out=[]
for i in range(0,len(pages),3):
    batch=pages[i:i+3]; t=time.time()
    try:
        r=call_vision('claude-opus','Extract all chemical structures as JSON array.',batch,system_prompt=SYS,max_tokens=4000,reasoning_effort='low',timeout=200)
        txt=r.text.strip().replace('```json','').replace('```','').strip()
        try: arr=json.loads(txt)
        except: arr=[]
        for o in (arr or []):
            cs=canon(o.get('smiles'))
            if cs: out.append({'label':o.get('label',''),'canon':cs})
        print('batch %d-%d (%.0fs) parsed=%d total_valid=%d'%(i,i+len(batch),time.time()-t,len(arr) if isinstance(arr,list) else 0,len(out)), flush=True)
    except Exception as e: print('err',repr(e)[:90], flush=True)
    json.dump(out, open('/root/scinex/chemx/results/claudepg_acsomega.2c06142.json','w'))
print('DONE', flush=True)
