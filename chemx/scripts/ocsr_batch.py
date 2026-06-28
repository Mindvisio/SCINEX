import os
os.environ['PYTORCH_CUDA_ALLOC_CONF']='max_split_size_mb:128'
import sys, json, glob, time
import numpy as np
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
ORGANIC={'C','H','N','O','S','P','F','Cl','Br','I','B','Si','Se'}
BZI=Chem.MolFromSmarts('c1ccc2ncnc2c1')
def classify(m):
    atoms=list(m.GetAtoms()); has_star=any(a.GetAtomicNum()==0 for a in atoms); n=len(atoms)
    real=set(a.GetSymbol() for a in atoms if a.GetAtomicNum()!=0)
    if n<5 or n>120 or not real: return 'noise'
    if len(real)==1 and not has_star: return 'noise'
    if [e for e in real if e not in ORGANIC]: return 'noise'
    if len(Chem.GetMolFrags(m))>4: return 'noise'
    return 'scaffold' if has_star else 'concrete'
def process(model, pdf, dpi=150, chunk=4, max_pages=16):
    import pdf2image, torch
    pages=pdf2image.convert_from_path(pdf, dpi=dpi, last_page=max_pages)
    imgs=[np.array(p) for p in pages]; allmol=[]
    for i in range(0,len(imgs),chunk):
        try:
            try: res=model.extract_molecules_from_figures(imgs[i:i+chunk], batch_size=8)
            except TypeError: res=model.extract_molecules_from_figures(imgs[i:i+chunk])
        except Exception: torch.cuda.empty_cache(); continue
        for fig in res:
            mols=fig.get('molecules',[]) if isinstance(fig,dict) else (fig if isinstance(fig,list) else [])
            allmol.extend(mols)
        torch.cuda.empty_cache()
    scaff={}; conc={}; raw=len(allmol)
    for md in allmol:
        smi=md.get('smiles') if isinstance(md,dict) else None
        if not smi: continue
        m=Chem.MolFromSmiles(smi)
        if m is None: continue
        c=classify(m)
        if c=='noise': continue
        can=Chem.MolToSmiles(m); bzi=bool(BZI) and m.HasSubstructMatch(BZI)
        d=scaff if c=='scaffold' else conc
        if can not in d: d[can]={'smiles':can,'bzi':bzi}
    return raw, list(scaff.values()), list(conc.values())
pdfs=sorted(glob.glob('/home/ubuntu/scinex/chemx/pdfs/*.pdf'))
from openchemie import OpenChemIE
print('loading OpenChemIE...', flush=True); model=OpenChemIE()
out={}
for pdf in pdfs:
    stem=pdf.split('/')[-1].replace('.pdf','')
    t=time.time()
    try: raw,scaff,conc=process(model,pdf)
    except Exception as e:
        print(stem,'ERR',repr(e)[:80],flush=True); out[stem]={'error':str(e)[:120]}; continue
    nb=sum(1 for c in conc if c['bzi'])
    print('%-26s raw=%-3d scaff=%-2d conc=%-3d bzi=%d %.0fs'%(stem,raw,len(scaff),len(conc),nb,time.time()-t),flush=True)
    out[stem]={'raw':raw,'scaffolds':scaff,'concretes':conc}
json.dump(out, open('/home/ubuntu/scinex/chemx/results/ocsr_pools_all.json','w'), indent=1)
print('BATCH_DONE')
