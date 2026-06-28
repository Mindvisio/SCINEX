import sys, glob, json, time
sys.path.insert(0,'/root/scinex')
from lib.llm_clients import call_vision
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
def canon(s):
    try: m=Chem.MolFromSmiles(str(s).strip()); return Chem.MolToSmiles(m) if m else None
    except: return None
SYS='You are an expert OCSR engine reading a journal page. Identify EVERY distinct chemical structure depiction (final compounds, scaffolds with R-groups expanded for each labelled variant). Output a JSON array of objects {"label":"<compound id or empty>","smiles":"<SMILES>"}. Expand Markush/R-table compounds into one entry per labelled variant. Output ONLY the JSON array, no prose, no code fences.'
pages=sorted(glob.glob('/tmp/intechpg/*.png'))
out=[]
for i in range(0,len(pages),3):
    batch=pages[i:i+3]; t=time.time()
    try:
        r=call_vision('gemini-pro','Extract all chemical structures as JSON array of {label,smiles}.',batch,system_prompt=SYS,max_tokens=3000,reasoning_effort='low',timeout=200)
        txt=r.text.strip().replace('```json','').replace('```','').strip()
        try: arr=json.loads(txt)
        except: arr=[]
        for o in (arr or []):
            cs=canon(o.get('smiles'))
            if cs: out.append({'label':o.get('label',''),'smiles':o.get('smiles'),'canon':cs})
        print('batch %s (%.0fs): parsed=%d valid_so_far=%d'%([p.split("/")[-1] for p in batch],time.time()-t,len(arr) if isinstance(arr,list) else 0,len(out)), flush=True)
    except Exception as e:
        print('batch err %s'%repr(e)[:100], flush=True)
    json.dump(out, open('/root/scinex/chemx/results/gempg_intechopen.json','w'))
print('GEMPG_DONE', flush=True)
