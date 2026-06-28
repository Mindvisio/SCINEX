import sys, glob, json, time
sys.path.insert(0,'/root/scinex')
from lib.llm_clients import call_vision
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
def canon(s):
    try: m=Chem.MolFromSmiles(str(s).strip()); return Chem.MolToSmiles(m) if m else None
    except: return None
SYS='You are an expert OCSR engine. The image is a single chemical structure depiction. Return ONLY the SMILES for the molecule, no prose, no code fences. If not a clear single molecule, return exactly NONE.'
stem=sys.argv[1]; N=int(sys.argv[2]) if len(sys.argv)>2 else 999
crops=sorted(glob.glob('/root/scinex/chemx/crops/%s/*.png'%stem))[:N]
out=[]
for i,c in enumerate(crops):
    t=time.time()
    try:
        r=call_vision('gemini-pro','Give the SMILES of this molecule.',[c],system_prompt=SYS,max_tokens=500,reasoning_effort='low',timeout=80)
        raw=r.text.strip().split('\n')[0][:120]; cs=canon(raw)
        out.append({'crop':c.split('/')[-1],'raw':raw,'canon':cs})
        print('%d/%d %-14s %.0fs -> %s'%(i+1,len(crops),c.split('/')[-1],time.time()-t,'valid' if cs else 'X'), flush=True)
    except Exception as e:
        out.append({'crop':c.split('/')[-1],'raw':None,'canon':None,'err':repr(e)[:120]})
        print('%d/%d %-14s ERR %s'%(i+1,len(crops),c.split('/')[-1],repr(e)[:90]), flush=True)
    json.dump(out, open('/root/scinex/chemx/results/gem_%s.json'%stem,'w'))
print('GEM_DONE', flush=True)
