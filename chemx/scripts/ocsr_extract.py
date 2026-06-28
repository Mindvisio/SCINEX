#!/usr/bin/env python
import os
os.environ['PYTORCH_CUDA_ALLOC_CONF']='max_split_size_mb:128'
import sys, json, glob, time
from collections import Counter
import numpy as np
from rdkit import Chem
from rdkit import RDLogger
RDLogger.DisableLog('rdApp.*')

ORGANIC = {'C','H','N','O','S','P','F','Cl','Br','I','B','Si','Se'}
BZI = Chem.MolFromSmarts('c1ccc2ncnc2c1')

def mol_from(smi):
    if not smi or not isinstance(smi,str): return None
    return Chem.MolFromSmiles(smi)

def is_noise(m):
    n = m.GetNumAtoms()
    if n < 5 or n > 120: return True,'size'
    uniq = set(a.GetSymbol() for a in m.GetAtoms())
    if len(uniq)==1: return True,'monoelement'
    if [e for e in uniq if e not in ORGANIC]: return True,'exotic'
    if len(Chem.GetMolFrags(m))>4: return True,'fragments'
    return False,''

def run(pdf, max_pages=14, dpi=150, chunk=4):
    import pdf2image, torch
    from openchemie import OpenChemIE
    pages = pdf2image.convert_from_path(pdf, dpi=dpi, first_page=1, last_page=max_pages)
    imgs = [np.array(p) for p in pages]
    print('PAGES',len(imgs),'dpi',dpi,'chunk',chunk,flush=True)
    model = OpenChemIE()
    allmol = []
    for i in range(0,len(imgs),chunk):
        sub = imgs[i:i+chunk]
        try:
            try: res = model.extract_molecules_from_figures(sub, batch_size=8)
            except TypeError: res = model.extract_molecules_from_figures(sub)
        except Exception as e:
            print('CHUNK_ERR',i,repr(e)[:90],flush=True); torch.cuda.empty_cache(); continue
        for fig in res:
            mols = fig.get('molecules',[]) if isinstance(fig,dict) else (fig if isinstance(fig,list) else [])
            allmol.extend(mols)
        torch.cuda.empty_cache()
        print('  chunk',i//chunk,'cum_mols',len(allmol),flush=True)
    keys = sorted(allmol[0].keys()) if allmol and isinstance(allmol[0],dict) else None
    raw=len(allmol); clean={}; reasons=Counter()
    for md in allmol:
        smi = md.get('smiles') if isinstance(md,dict) else None
        score=None
        if isinstance(md,dict):
            for k in ('score','confidence','prob','mol_score'):
                if k in md: score=md[k]; break
        m = mol_from(smi)
        if m is None: reasons['unparseable']+=1; continue
        noise,why = is_noise(m)
        if noise: reasons[why]+=1; continue
        can = Chem.MolToSmiles(m)
        try: ik = Chem.MolToInchiKey(m)
        except Exception: ik = can
        bzi = bool(BZI) and m.HasSubstructMatch(BZI)
        if ik not in clean or (score or 0)>(clean[ik]['score'] or 0):
            clean[ik]={'smiles':can,'score':score,'bzi':bzi}
    return raw,clean,reasons,keys

if __name__=='__main__':
    pdf = sys.argv[1] if len(sys.argv)>1 else sorted(glob.glob('/home/ubuntu/scinex/chemx/pdfs/*.pdf'))[0]
    t=time.time(); raw,clean,reasons,keys = run(pdf)
    stem = pdf.split('/')[-1].replace('.pdf','')
    pool = sorted(clean.values(), key=lambda x:-(x['score'] or 0))
    nbzi = sum(1 for v in clean.values() if v['bzi'])
    print('PDF',stem,'time %.1fs'%(time.time()-t))
    print('MOL_KEYS',keys)
    print('RAW',raw,'CLEAN',len(clean),'BENZIMIDAZOLE_CORE',nbzi)
    print('REJECT',dict(reasons))
    print('--- clean pool ---')
    for v in pool: print('  %s  score=%s bzi=%s'%(v['smiles'],v['score'],v['bzi']))
    out='/home/ubuntu/scinex/chemx/results/ocsr_pool_%s.json'%stem
    json.dump({'pdf':stem,'raw':raw,'clean':len(clean),'bzi':nbzi,'pool':pool},open(out,'w'),indent=1)
    print('SAVED',out); print('OCSR_EXTRACT_DONE')
