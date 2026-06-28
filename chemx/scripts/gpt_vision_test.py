import sys, glob, json, time
sys.path.insert(0,'/root/scinex')
from lib.llm_clients import call_vision
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
def canon(s):
    try: m=Chem.MolFromSmiles(str(s).strip()); return Chem.MolToSmiles(m) if m else None
    except: return None
SYS='Expert OCSR. Identify every distinct chemical structure on these pages. Output ONLY a JSON array of {"label":"","smiles":""}. No prose, no fences.'
pages=sorted(glob.glob('/tmp/antibpg/*.png'))[6:9]
t=time.time()
try:
    r=call_vision('gpt-5.5-pro','Extract all chemical structures as JSON array.',pages,system_prompt=SYS,max_tokens=4000,reasoning_effort='medium',timeout=270)
    txt=r.text.strip().replace('```json','').replace('```','').strip()
    try: arr=json.loads(txt)
    except: arr=[]
    valid=[v for v in (canon(o.get('smiles')) for o in (arr or [])) if v]
    json.dump(valid, open('/root/scinex/chemx/results/gpt_test.json','w'))
    print('GPT-5.5 OK %.0fs parsed=%d valid=%d'%(time.time()-t,len(arr) if isinstance(arr,list) else 0,len(valid)), flush=True)
except Exception as e:
    print('GPT-5.5 ERR %.0fs %s'%(time.time()-t,repr(e)[:160]), flush=True)
print('DONE', flush=True)
