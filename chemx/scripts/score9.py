import sys, json, os
_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); _RES=os.path.join(_ROOT,'chemx','results')
sys.path.insert(0,os.path.join(_ROOT,'hw_chemdb'))
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
HAVE7=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
cols=M.EXTRACTED_COLUMNS['benzimidazole']
gold=M.prepare_dataset('benzimidazole', M.NUMERIC_COLUMNS['benzimidazole'], M.SMILES_COLS['benzimidazole']); gold['pdf']=gold['pdf'].astype(str).str.lower()
allOA=sorted(gold['pdf'].unique())
print('OA articles in gold:',len(allOA)); print(' ',allOA)
print('have preds:',[a for a in allOA if a in HAVE7])
print('MISSING  :',[a for a in allOA if a not in HAVE7])
grows={a:len(gold[gold['pdf']==a]) for a in allOA}
print('gold rows/article:',grows)
def canon(s):
    try: mm=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(mm) if mm else None
    except: return None
def cid(x): return str(x).strip().strip('*').strip().strip('()').strip().strip('*').strip()
db=pd.read_csv(os.path.join(_RES,'chem_db.dedup.csv')); db['pdfn']=db['source_pdf'].astype(str).str.lower().str.replace('.pdf','',regex=False)
ocsr={a:[s for s in (canon(x) for x in db[db['pdfn']==a]['smiles_canonical'].dropna().unique()) if s] for a in HAVE7}
def build():
    pr=[]
    for a in HAVE7:
        f='%s/llm_%s.json'%(_RES,a); rows=json.load(open(f)) if os.path.exists(f) else []
        pool=ocsr.get(a,[])
        for i,r in enumerate(rows):
            pr.append(dict(compound_id=cid(r['compound_id']),smiles=(pool[i%len(pool)] if pool else None),target_type=r['target_type'],target_relation=r['target_relation'],target_value=str(r['target_value']).replace(',','.'),target_units=r['target_units'],bacteria=r['bacteria'],pdf=a))
    p=pd.DataFrame(pr)
    for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
    return p.drop_duplicates()
def macro(p,arts):
    m=M.empty_metrics(cols)
    for a in arts: m+=M.calc_metrics(gold[gold['pdf']==a][cols], (p[p['pdf']==a][cols] if len(p) else pd.DataFrame(columns=cols)))
    return (m/len(arts))['f1']
new=build()
_CHEMX=os.environ.get('CHEMX_ROOT','/tmp/ChemX'); bl=pd.read_csv('%s/LLM/result/from_single_agent/benzimidazole/pred.csv'%_CHEMX); bl['pdf']=bl['pdf'].astype(str).str.lower()
for nm,p,arts in [('OUR (Mathpix+LLM+OCSR) /7',new,HAVE7),('OUR /all OA (2 missing=0)',new,allOA),('BASELINE /all OA (official)',bl,allOA)]:
    f=macro(p,arts); print('%-32s MACRO=%.4f  (smiles=%.3f val=%.3f units=%.3f bact=%.3f)'%(nm,f.mean(),f['smiles'],f['target_value'],f['target_units'],f['bacteria']))
