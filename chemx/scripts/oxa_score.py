import sys, json, os
_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); _RES=os.path.join(_ROOT,'chemx','results')
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(_ROOT,'hw_chemdb'))
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
from normalize import micro_norm
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else str(s)
    except: return str(s)
cols=M.EXTRACTED_COLUMNS['oxazolidinone']
g=M.prepare_dataset('oxazolidinone', M.NUMERIC_COLUMNS['oxazolidinone'], M.SMILES_COLS['oxazolidinone']); g['pdf']=g['pdf'].astype(str)
PAPERS=['molecules27031103','ph16040516']
_CHEMX=os.environ.get('CHEMX_ROOT','/tmp/ChemX')
base=pd.read_csv('%s/LLM/result/from_single_agent/oxazolidinone/pred.csv'%_CHEMX).fillna('NOT_DETECTED'); base['pdf']=base['pdf'].astype(str)
for c in M.SMILES_COLS['oxazolidinone']: base[c]=base[c].apply(lambda x: canon(x) if Chem.MolFromSmiles(str(x)) else x)
def build(titlecase_bact):
    pr=[]
    for stem in PAPERS:
        rows=json.load(open('%s/llm_%s.json'%(_RES,stem)))
        smap=json.load(open('%s/oxa_smiles_%s.json'%(_RES,stem))) if os.path.exists('%s/oxa_smiles_%s.json'%(_RES,stem)) else {}
        for r in rows:
            cid=str(r['compound_id']).strip(); b=str(r['bacteria'])
            pr.append(dict(compound_id=cid, smiles=smap.get(cid,'NOT_DETECTED'), target_type=r['target_type'], target_relation=r['target_relation'], target_value=str(r['target_value']).replace(',','.'), target_units=micro_norm(r['target_units'],'oxazolidinone'), bacteria=(b.title() if titlecase_bact else b), pdf=stem))
    p=pd.DataFrame(pr)
    for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
    return p.drop_duplicates()
def macro(pred):
    m=M.empty_metrics(cols)
    for a in PAPERS: m+=M.calc_metrics(g[g['pdf']==a][cols], pred[pred['pdf']==a][cols])
    return m/len(PAPERS)
bm=macro(base); raw=macro(build(False)); ali=macro(build(True))
print('OXAZOLIDINONE end-to-end (2 papers), official metric')
print('%-18s %8s %10s %10s'%('column','baseline','ours','ours+bactAlign'))
for c in cols: print('  %-16s %8.3f %10.3f %10.3f'%(c, bm['f1'][c], raw['f1'][c], ali['f1'][c]))
print('  %-16s %8.4f %10.4f %10.4f'%('MACRO', bm['f1'].mean(), raw['f1'].mean(), ali['f1'].mean()))
