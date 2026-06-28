import os
os.environ['PYTORCH_CUDA_ALLOC_CONF']='max_split_size_mb:128'
import sys, io, json, glob
from collections import Counter
import numpy as np, fitz
from PIL import Image
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
import torch
from openchemie import OpenChemIE
BZI=Chem.MolFromSmarts('c1ccc2ncnc2c1')
def figs(pdf):
    doc=fitz.open(pdf); out=[]; seen=set()
    for pno in range(len(doc)):
        for img in doc[pno].get_images(full=True):
            x=img[0]
            if x in seen: continue
            seen.add(x)
            try:
                d=doc.extract_image(x); im=Image.open(io.BytesIO(d['image'])).convert('RGB')
                if im.width<120 or im.height<120: continue
                if im.width*im.height>4000000: continue
                out.append(np.array(im))
            except Exception: pass
    return out
model=OpenChemIE(); RES='/home/ubuntu/scinex/chemx/results'
for pdf in sorted(glob.glob('/home/ubuntu/scinex/chemx/pdfs/*.pdf')):
    stem=os.path.basename(pdf)[:-4]; imgs=figs(pdf); cand=Counter()
    for arr in imgs:
        try:
            try: res=model.extract_molecules_from_figures([arr],batch_size=4)
            except TypeError: res=model.extract_molecules_from_figures([arr])
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
                na=mol.GetNumAtoms()
                if na<6 or na>120: continue
                cand[Chem.MolToSmiles(mol)]+=1
        torch.cuda.empty_cache()
    ranked=sorted(cand.items(), key=lambda kv:(Chem.MolFromSmiles(kv[0]).HasSubstructMatch(BZI), kv[1], Chem.MolFromSmiles(kv[0]).GetNumAtoms()), reverse=True)
    best=ranked[0][0] if ranked else None
    json.dump({'pdf':stem,'scaffold':best,'candidates':dict(cand)}, open('%s/scaffold_%s.json'%(RES,stem),'w'), indent=1)
    print('%-26s figs=%-3d cands=%-3d scaffold=%s'%(stem,len(imgs),len(cand),(best[:68] if best else 'NONE')), flush=True)
print('SCAFFOLD_DONE', flush=True)
