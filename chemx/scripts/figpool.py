import os
os.environ['PYTORCH_CUDA_ALLOC_CONF']='max_split_size_mb:128'
import io, json, glob
import numpy as np, fitz, pdf2image
from PIL import Image
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
import torch
from openchemie import OpenChemIE
BZI=Chem.MolFromSmarts('c1ccc2ncnc2c1')
def complete(s):
    m=Chem.MolFromSmiles(s)
    if m is None: return None
    if any(a.GetAtomicNum()==0 for a in m.GetAtoms()): return None
    if len(Chem.GetMolFrags(m))!=1: return None
    n=m.GetNumHeavyAtoms()
    if n<10 or n>80: return None
    if not m.HasSubstructMatch(BZI): return None
    return Chem.MolToSmiles(m)
def emb(pdf):
    doc=fitz.open(pdf); out=[]; seen=set()
    for pno in range(len(doc)):
        for img in doc[pno].get_images(full=True):
            x=img[0]
            if x in seen: continue
            seen.add(x)
            try:
                d=doc.extract_image(x); im=Image.open(io.BytesIO(d['image'])).convert('RGB')
                if im.width<120 or im.height<120 or im.width*im.height>4000000: continue
                out.append(np.array(im))
            except: pass
    return out
model=OpenChemIE(); RES='/home/ubuntu/scinex/chemx/results'
for pdf in sorted(glob.glob('/home/ubuntu/scinex/chemx/pdfs/*.pdf')):
    stem=os.path.basename(pdf)[:-4]; imgs=emb(pdf)
    if not imgs:
        try: imgs=[np.array(p) for p in pdf2image.convert_from_path(pdf,dpi=200,last_page=20)]
        except: imgs=[]
    pool=set()
    for i in range(0,len(imgs),3):
        chunk=imgs[i:i+3]
        try:
            try: res=model.extract_molecules_from_figures(chunk,batch_size=4)
            except TypeError: res=model.extract_molecules_from_figures(chunk)
        except: torch.cuda.empty_cache(); continue
        for fig in res:
            ms=fig.get('molecules',[]) if isinstance(fig,dict) else (fig if isinstance(fig,list) else [])
            for m in ms:
                s=m.get('smiles') if isinstance(m,dict) else None
                if not s: continue
                c=complete(s)
                if c: pool.add(c)
        torch.cuda.empty_cache()
    json.dump(sorted(pool), open('%s/figpool_%s.json'%(RES,stem),'w'))
    print('%-26s imgs=%-3d figpool=%d'%(stem,len(imgs),len(pool)), flush=True)
print('FIGPOOL_DONE', flush=True)
