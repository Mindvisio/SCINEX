import os
os.environ['PYTORCH_CUDA_ALLOC_CONF']='max_split_size_mb:128'
import io, json, glob, collections
import numpy as np, fitz, pdf2image
from PIL import Image
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
import torch
from openchemie import OpenChemIE
CORE=Chem.MolFromSmarts('O=C1OCCN1')
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else None
    except: return None
def complete(s):
    m=Chem.MolFromSmiles(s)
    if m is None or any(a.GetAtomicNum()==0 for a in m.GetAtoms()) or len(Chem.GetMolFrags(m))!=1: return None
    n=m.GetNumHeavyAtoms()
    if n<12 or n>90 or not m.HasSubstructMatch(CORE): return None
    return Chem.MolToSmiles(m)
def scaf_cand(s):
    m=Chem.MolFromSmiles(s)
    if m is None: return None
    dummies=[a for a in m.GetAtoms() if a.GetAtomicNum()==0]
    if len(dummies)!=1 or len(Chem.GetMolFrags(m))!=1: return None
    n=m.GetNumHeavyAtoms()
    if n<8 or n>90 or not m.HasSubstructMatch(CORE): return None
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
                if im.width<110 or im.height<110 or im.width*im.height>5000000: continue
                out.append(np.array(im))
            except: pass
    return out
model=OpenChemIE(); RES='/home/ubuntu/scinex/chemx/results'
for stem in ['molecules27031103','ph16040516']:
    pdf='/home/ubuntu/scinex/chemx/pdfs/%s.pdf'%stem
    imgs=emb(pdf)
    if len(imgs)<2:
        try: imgs=[np.array(p) for p in pdf2image.convert_from_path(pdf,dpi=200,last_page=20)]
        except: pass
    pool=set(); scafs=collections.Counter()
    for i in range(0,len(imgs),3):
        chunk=imgs[i:i+3]
        try:
            try: res=model.extract_molecules_from_figures(chunk,batch_size=4)
            except TypeError: res=model.extract_molecules_from_figures(chunk)
        except: torch.cuda.empty_cache(); continue
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
    top=scafs.most_common(8)
    json.dump({'scaffold':(top[0][0] if top else None),'candidates':top}, open('%s/scaffold_%s.json'%(RES,stem),'w'))
    print('%-20s imgs=%-3d pool=%-3d scaffolds=%d top=%s'%(stem,len(imgs),len(pool),len(scafs),(top[0] if top else None)), flush=True)
print('OXA_OCSR_DONE', flush=True)
