import sys,re,json,os; sys.path.insert(0,'/root/scinex/hw_chemdb'); sys.path.insert(0,'.')
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
from normalize import micro_norm
def nk(x): return re.sub('[^a-z0-9]','',str(x).lower().replace('.pdf',''))
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else str(s)
    except: return str(s)
CACHE=json.load(open('/tmp/pubchem_cache.json')) if os.path.exists('/tmp/pubchem_cache.json') else {}
NAMEMAP={'cocrystals':[('name_drug','SMILES_drug'),('name_coformer','SMILES_coformer')],'complexes':[('compound_name','SMILES')]}
DS=[('oxazolidinone','oxazolidinone'),('cocrystals','cocrystals'),('complexes','complexes'),('nanozymes','nanozymes'),('magnetic','magnetic'),('cytotoxicity','cytotoxicity'),('seltox','seltox'),('synergy','synergy')]
rows=[]
for ds,pname in DS:
    cols=M.EXTRACTED_COLUMNS[ds]
    g=M.prepare_dataset(ds, M.NUMERIC_COLUMNS[ds], M.SMILES_COLS[ds])
    pred=pd.read_csv('/tmp/ChemX/LLM/result/from_single_agent/%s/pred.csv'%pname).fillna('NOT_DETECTED')
    for c in M.SMILES_COLS[ds]: pred[c]=pred[c].apply(lambda x: canon(x) if Chem.MolFromSmiles(str(x)) is not None else x)
    # baseline (official key)
    gp=g.copy(); gp['pk']=gp['pdf'].astype(str).str.lower(); prb=pred.copy(); prb['pk']=(pred['pdf'].astype(str)+'.pdf').str.lower()
    def macro(gdf,pdf_,key,arts):
        m=M.empty_metrics(cols)
        for a in arts: m+=M.calc_metrics(gdf[gdf[key]==a][cols], pdf_[pdf_[key]==a][cols])
        return (m/len(arts))['f1']
    base=macro(gp,prb,'pk',sorted(gp['pk'].unique())).mean()
    # +levers: normalized key + units unicode + name->pubchem
    g['k']=g['pdf'].apply(nk); pr=pred.copy(); pr['k']=pred['pdf'].apply(nk)
    for c in pr.columns:
        if 'unit' in c.lower(): pr[c]=pr[c].apply(lambda x: micro_norm(x, ds))
    for ncol,scol in NAMEMAP.get(ds,[]):
        pr[scol]=pr.apply(lambda r: (CACHE.get(str(r[ncol]).strip()) or r[scol]), axis=1)
    fix=macro(g,pr,'k',sorted(g['k'].unique())).mean()
    rows.append((ds,base,fix,fix-base)); print('%-13s baseline=%.4f  all-levers=%.4f  (+%.4f)'%(ds,base,fix,fix-base))
import statistics
b=statistics.mean(r[1] for r in rows); f=statistics.mean(r[2] for r in rows)
print('-'*60)
print('8-domain avg Macro: baseline=%.4f -> all-levers=%.4f (+%.4f)'%(b,f,f-b))
print('(+ benzimidazole our OCSR pipeline: /allOA 0.3840->0.3921; /7 0.4937->0.5039)')
