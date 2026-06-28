import os
os.environ['PYTORCH_CUDA_ALLOC_CONF']='max_split_size_mb:128'
import json
from collections import Counter
import numpy as np, pdf2image
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
import torch
from openchemie import OpenChemIE
BZI=Chem.MolFromSmarts('c1ccc2ncnc2c1')
model=OpenChemIE(); RES='/home/ubuntu/scinex/chemx/results'
for stem in ['intechopen.108949','s13065-018-0479-1']:
    pages=pdf2image.convert_from_path('/home/ubuntu/scinex/chemx/pdfs/%s.pdf'%stem, dpi=200, last_page=20)
    cand=Counter()
    for i in range(0,len(pages),3):
        imgs=[np.array(p) for p in pages[i:i+3]]
        try:
            try: res=model.extract_molecules_from_figures(imgs,batch_size=4)
            except TypeError: res=model.extract_molecules_from_figures(imgs)
        except Exception: torch.cuda.empty_cache(); continue
        for fig in res:
            ms=fig.get('molecules',[]) if isinstance(fig,dict) else (fig if isinstance(fig,list) else [])
            for m in ms:
                s=m.get('smiles') if isinstance(m,dict) else None
                if not s: continue
                mol=Chem.MolFromSmiles(s)
                if mol is None: continue
                if sum(1 for a in mol.GetAtoms() if a.GetAtomicNum()==0)!=1: continue
                if len(Chem.GetMolFrags(mol))!=1: continue
                if not (6<=mol.GetNumAtoms()<=120): continue
                cand[Chem.MolToSmiles(mol)]+=1
        torch.cuda.empty_cache()
    ranked=sorted(cand.items(), key=lambda kv:(Chem.MolFromSmiles(kv[0]).HasSubstructMatch(BZI),kv[1],Chem.MolFromSmiles(kv[0]).GetNumAtoms()), reverse=True)
    best=ranked[0][0] if ranked else None
    json.dump({'pdf':stem,'scaffold':best,'candidates':dict(cand)}, open('%s/scaffold_%s.json'%(RES,stem),'w'), indent=1)
    print('%-26s pages=%-3d cands=%-3d scaffold=%s'%(stem,len(pages),len(cand),(best[:68] if best else 'NONE')),flush=True)
print('RENDER_SCAF_DONE',flush=True)
