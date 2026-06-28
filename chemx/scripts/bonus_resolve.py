import sys,urllib.parse,urllib.request,time,json,os
sys.path.insert(0,'/root/scinex/hw_chemdb'); sys.path.insert(0,'.')
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
from normalize import micro_norm
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else str(s)
    except: return str(s)
CACHE_F='/tmp/pubchem_cache.json'
CACHE=json.load(open(CACHE_F)) if os.path.exists(CACHE_F) else {}
def pubchem(name):
    name=str(name).strip()
    if not name or name=='NOT_DETECTED': return None
    if name in CACHE: return CACHE[name]
    res=None
    for prop in ['IsomericSMILES','CanonicalSMILES']:
        try:
            u='https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s/property/%s/TXT'%(urllib.parse.quote(name),prop)
            r=urllib.request.urlopen(u,timeout=20).read().decode().strip().split('\n')[0]
            if r and 'Status' not in r and 'Fault' not in r: res=canon(r); break
        except Exception: pass
    CACHE[name]=res; time.sleep(0.22); return res
def run(ds, pname, name2smiles):
    cols=M.EXTRACTED_COLUMNS[ds]
    g=M.prepare_dataset(ds, M.NUMERIC_COLUMNS[ds], M.SMILES_COLS[ds]); g['pdf']=g['pdf'].astype(str)
    pred=pd.read_csv('/tmp/ChemX/LLM/result/from_single_agent/%s/pred.csv'%pname).fillna('NOT_DETECTED'); pred['pdf']=pred['pdf'].astype(str)
    for c in M.SMILES_COLS[ds]:
        pred[c]=pred[c].apply(lambda x: canon(x) if Chem.MolFromSmiles(str(x)) is not None else x)
    arts=sorted(g['pdf'].unique())
    def macro(pr):
        m=M.empty_metrics(cols)
        for a in arts: m+=M.calc_metrics(g[g['pdf']==a][cols], pr[pr['pdf']==a][cols])
        return m/len(arts)
    base=macro(pred)
    pred2=pred.copy()
    # units unicode norm on any unit-like column present
    for c in pred2.columns:
        if 'unit' in c.lower(): pred2[c]=pred2[c].apply(lambda x: micro_norm(x, ds))
    # name->smiles resolution
    for ncol,scol in name2smiles:
        names=[n for n in pred2[ncol].unique() if str(n)!='NOT_DETECTED']
        for n in names: pubchem(n)
        json.dump(CACHE,open(CACHE_F,'w'))
        pred2[scol]=pred2.apply(lambda r: (CACHE.get(str(r[ncol]).strip()) or r[scol]), axis=1)
    impr=macro(pred2)
    print('%-12s baseline Macro=%.4f  ->  +resolve+units Macro=%.4f  (delta +%.4f)'%(ds,base['f1'].mean(),impr['f1'].mean(),impr['f1'].mean()-base['f1'].mean()))
    for c in cols:
        if abs(impr['f1'][c]-base['f1'][c])>1e-4: print('     %-22s %.3f -> %.3f'%(c,base['f1'][c],impr['f1'][c]))
run('cocrystals','cocrystals',[('name_drug','SMILES_drug'),('name_coformer','SMILES_coformer')])
run('complexes','complexes',[('compound_name','SMILES')])
