import os
os.environ['PYTORCH_CUDA_ALLOC_CONF']='max_split_size_mb:128'
import json, collections
import numpy as np, pdf2image
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
import torch
from openchemie import OpenChemIE
CORE=Chem.MolFromSmarts('O=C1OCCN1')
def complete(s):
    m=Chem.MolFromSmiles(s)
    if m is None or any(a.GetAtomicNum()==0 for a in m.GetAtoms()) or len(Chem.GetMolFrags(m))!=1: return None
    n=m.GetNumHeavyAtoms()
    if n<12 or n>90 or not m.HasSubstructMatch(CORE): return None
    return Chem.MolToSmiles(m)
def scaf_cand(s):
    m=Chem.MolFromSmiles(s)
    if m is None: return None
    if len([a for a in m.GetAtoms() if a.GetAtomicNum()==0])!=1 or len(Chem.GetMolFrags(m))!=1: return None
    n=m.GetNumHeavyAtoms()
    if n<8 or n>90 or not m.HasSubstructMatch(CORE): return None
    return Chem.MolToSmiles(m)
model=OpenChemIE(); RES='/home/ubuntu/scinex/chemx/results'
for stem in ['molecules27031103','ph16040516']:
    pdf='/home/ubuntu/scinex/chemx/pdfs/%s.pdf'%stem
    try: pages=[np.array(p) for p in pdf2image.convert_from_path(pdf,dpi=250,last_page=20)]
    except Exception as e: print(stem,'render err',e,flush=True); pages=[]
    pool=set(json.load(open('%s/figpool_%s.json'%(RES,stem)))) if os.path.exists('%s/figpool_%s.json'%(RES,stem)) else set()
    scafs=collections.Counter()
    for i in range(0,len(pages),2):
        chunk=pages[i:i+2]
        try:
            try: res=model.extract_molecules_from_figures(chunk,batch_size=2)
            except TypeError: res=model.extract_molecules_from_figures(chunk)
        except Exception: torch.cuda.empty_cache(); continue
        for fig in res:
            ms=fig.get('molecules',[]) if isinstance(fig,dict) else (fig if isinstance(fig,list) else [])
            for mm in ms:
                s=mm.get('smiles') if isinstance(mm,dict) else None
                if not s: continue
                c=complete(s)
                if c: pool.add(c)
                sc=scaf_cand(s)
                if sc: scafs[sc]+=1
        torch.cuda.empty_cache()
    json.dump(sorted(pool), open('%s/figpool_%s.json'%(RES,stem),'w'))
    top=scafs.most_common(10)
    json.dump({'scaffold':(top[0][0] if top else None),'candidates':top}, open('%s/scaffold_%s.json'%(RES,stem),'w'))
    print('%-20s pages=%-3d pool=%-3d scaffolds=%d top=%s'%(stem,len(pages),len(pool),len(scafs),(top[0] if top else None)), flush=True)
print('OXA_RENDER_DONE', flush=True)
