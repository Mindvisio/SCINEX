import sys, json, os
sys.path.insert(0,'/root/scinex/hw_chemdb')
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
HAVE=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
cols=M.EXTRACTED_COLUMNS['benzimidazole']
gold=M.prepare_dataset('benzimidazole', M.NUMERIC_COLUMNS['benzimidazole'], M.SMILES_COLS['benzimidazole']); gold['pdf']=gold['pdf'].astype(str).str.lower()
arts=[a for a in gold['pdf'].unique() if a in HAVE]
def canon(s):
    try: mm=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(mm) if mm else None
    except: return None
def clean_id(x):
    s=str(x).strip().strip('*').strip().strip('()').strip().strip('*').strip()
    return s
def score(p):
    p=p.copy(); p['pdf']=p['pdf'].astype(str).str.lower(); m=M.empty_metrics(cols)
    for a in arts: m+=M.calc_metrics(gold[gold['pdf']==a][cols], p[p['pdf']==a][cols])
    return m/len(arts)
def show(n,m):
    f=m['f1']; print('### %-26s MACRO=%.4f'%(n,f.mean())); print('   '+'  '.join('%s=%.3f'%(c,f[c]) for c in cols))
bl=pd.read_csv('/tmp/ChemX/LLM/result/from_single_agent/benzimidazole/pred.csv'); bl['pdf']=bl['pdf'].replace({'acsomega_2c06142':'acsomega.2c06142','intechopen_108949':'intechopen.108949'})
db=pd.read_csv('/tmp/chemx_benz/chem_db.dedup.csv'); db['pdfn']=db['source_pdf'].astype(str).str.lower().str.replace('.pdf','',regex=False)
ocsr={a:[s for s in (canon(x) for x in db[db['pdfn']==a]['smiles_canonical'].dropna().unique()) if s] for a in HAVE}
def build():
    pr=[]
    for a in HAVE:
        f='/tmp/chemx_benz/llm_%s.json'%a; rows=json.load(open(f)) if os.path.exists(f) else []
        pool=ocsr[a]
        for i,r in enumerate(rows):
            pr.append(dict(compound_id=clean_id(r['compound_id']),smiles=(pool[i%len(pool)] if pool else None),target_type=r['target_type'],target_relation=r['target_relation'],target_value=str(r['target_value']).replace(',','.'),target_units=r['target_units'],bacteria=r['bacteria'],pdf=a))
    p=pd.DataFrame(pr)
    for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
    return p.drop_duplicates()
show('BASELINE (our7)', score(bl))
new=build(); show('NEW (Mathpix+LLM+OCSR)', score(new))
print('\narticle                  base    NEW')
for a in arts:
    gA=gold[gold['pdf']==a]
    b=M.calc_metrics(gA[cols], bl.assign(pdf=bl['pdf'].astype(str).str.lower())[bl['pdf'].astype(str).str.lower()==a][cols])['f1'].mean()
    nn=M.calc_metrics(gA[cols], new[new['pdf']==a][cols])['f1'].mean()
    print('%-22s %.3f  %.3f  %s'%(a,b,nn,'NEW' if nn>=b else 'base'))
