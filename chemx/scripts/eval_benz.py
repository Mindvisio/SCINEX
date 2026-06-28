import sys, re
sys.path.insert(0,'/root/scinex/hw_chemdb')
import pandas as pd
import metric_local as M
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')

HAVE=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
cols=M.EXTRACTED_COLUMNS['benzimidazole']
gold=M.prepare_dataset('benzimidazole', M.NUMERIC_COLUMNS['benzimidazole'], M.SMILES_COLS['benzimidazole'])
gold['pdf']=gold['pdf'].astype(str).str.lower()
arts=[a for a in gold['pdf'].unique() if a in HAVE]

def score(pred):
    pred=pred.copy(); pred['pdf']=pred['pdf'].astype(str).str.lower()
    m=M.empty_metrics(cols)
    for a in arts: m+=M.calc_metrics(gold[gold['pdf']==a][cols], pred[pred['pdf']==a][cols])
    return m/len(arts)
def show(name,m):
    f=m['f1']; print('### %-26s MACRO-F1=%.4f'%(name,f.mean()))
    print('   '+'  '.join('%s=%.3f'%(c,f[c]) for c in cols))

# BASELINE on our 7
bl=pd.read_csv('/tmp/ChemX/LLM/result/from_single_agent/benzimidazole/pred.csv')
bl['pdf']=bl['pdf'].replace({'acsomega_2c06142':'acsomega.2c06142','intechopen_108949':'intechopen.108949'})
show('BASELINE (our7)', score(bl))
print()

df=pd.read_csv('/tmp/chemx_benz/chem_db.dedup.csv')
def pdfn(s): s=str(s); return (s[:-4] if s.lower().endswith('.pdf') else s).lower()
def canon(s):
    if s is None or (isinstance(s,float) and pd.isna(s)): return None
    m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else str(s)
def cleanval(v):
    if pd.isna(v): return None
    s=str(v).strip().replace(',','.'); s=re.sub(r'^[<>=~\u2264\u2265]+','',s).strip()
    try: return '%g'%float(s)
    except: return s or None
df['pdfn']=df['source_pdf'].apply(pdfn)

def build(mic_only=True, add_struct=False):
    rows=[]
    sub=df[df['property']=='MIC'] if mic_only else df
    for _,r in sub.iterrows():
        rows.append(dict(compound_id=r.get('name_raw'), smiles=canon(r.get('smiles_canonical')),
            target_type=('MIC' if mic_only else r.get('property')), target_relation='=',
            target_value=cleanval(r.get('value_raw')), target_units=r.get('unit_raw'),
            bacteria=r.get('organism_raw'), pdf=r['pdfn']))
    if add_struct:
        for _,r in df[df['smiles_canonical'].notna()].iterrows():
            rows.append(dict(compound_id=r.get('name_raw'), smiles=canon(r.get('smiles_canonical')),
                target_type=None, target_relation='=', target_value=None,
                target_units=None, bacteria=None, pdf=r['pdfn']))
    p=pd.DataFrame(rows)
    for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
    return p.drop_duplicates()

show('MIC-only', score(build(True,False)))
show('MIC + all structures', score(build(True,True)))
show('ALL rows (no filter)', score(build(False,False)))
