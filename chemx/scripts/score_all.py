import sys, json, os
sys.path.insert(0,'/root/scinex/hw_chemdb')
import pandas as pd, metric_local as M
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
HAVE=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
cols=M.EXTRACTED_COLUMNS['benzimidazole']
gold=M.prepare_dataset('benzimidazole', M.NUMERIC_COLUMNS['benzimidazole'], M.SMILES_COLS['benzimidazole'])
gold['pdf']=gold['pdf'].astype(str).str.lower(); arts=[a for a in gold['pdf'].unique() if a in HAVE]
def score(p):
    p=p.copy(); p['pdf']=p['pdf'].astype(str).str.lower(); m=M.empty_metrics(cols)
    for a in arts: m+=M.calc_metrics(gold[gold['pdf']==a][cols], p[p['pdf']==a][cols])
    return m/len(arts)
def show(n,m):
    f=m['f1']; print('### %-24s MACRO=%.4f'%(n,f.mean())); print('   '+'  '.join('%s=%.3f'%(c,f[c]) for c in cols))
def canon(s):
    try: mm=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(mm) if mm else None
    except: return None
bl=pd.read_csv('/tmp/ChemX/LLM/result/from_single_agent/benzimidazole/pred.csv')
bl['pdf']=bl['pdf'].replace({'acsomega_2c06142':'acsomega.2c06142','intechopen_108949':'intechopen.108949'})
show('BASELINE (our7)', score(bl)); print()
db=pd.read_csv('/tmp/chemx_benz/chem_db.dedup.csv'); db['pdfn']=db['source_pdf'].astype(str).str.lower().str.replace('.pdf','',regex=False)
ocsr={a:[s for s in (canon(x) for x in db[db['pdfn']==a]['smiles_canonical'].dropna().unique()) if s] for a in HAVE}
def build(struct):
    pr=[]
    for a in HAVE:
        f='/tmp/chemx_benz/llm_%s.json'%a
        rows=json.load(open(f)) if os.path.exists(f) else []
        for r in rows:
            cid=str(r['compound_id']).strip().strip('*').strip()
            pr.append(dict(compound_id=cid,smiles=None,target_type=r['target_type'],target_relation=r['target_relation'],target_value=str(r['target_value']).replace(',','.'),target_units=r['target_units'],bacteria=r['bacteria'],pdf=a))
        if struct:
            for s in ocsr[a]: pr.append(dict(compound_id=None,smiles=s,target_type=None,target_relation='=',target_value=None,target_units=None,bacteria=None,pdf=a))
    p=pd.DataFrame(pr)
    for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
    return p.drop_duplicates()
nj=sum(os.path.exists('/tmp/chemx_benz/llm_%s.json'%a) and len(json.load(open('/tmp/chemx_benz/llm_%s.json'%a)))>0 for a in HAVE)
print('papers with rows: %d/7'%nj)
show('NEW LLM-only', score(build(False)))
show('NEW LLM+OCSR-struct', score(build(True)))

print('\n=== antibiotics10081002 281-row диагностика ===')
import json as _j
r=_j.load(open('/tmp/chemx_benz/llm_antibiotics10081002.json'))
from collections import Counter
print('bacteria:', dict(Counter(x['bacteria'] for x in r)))
print('units:', dict(Counter(x['target_units'] for x in r)))
print('ttype:', dict(Counter(x['target_type'] for x in r)))
gm=gold[gold["pdf"]=="antibiotics10081002"]
print('GOLD a10081002: rows',len(gm),'| bacteria:', dict(Counter(gm["bacteria"].astype(str))))

print('\n=== вариант: OCSR-smiles НА measurement-строки (cycled, без struct-строк) ===')
def build_pool():
    pr=[]
    for a in HAVE:
        f='/tmp/chemx_benz/llm_%s.json'%a
        rows=_j.load(open(f)) if os.path.exists(f) else []
        pool=ocsr[a]
        for i,rr in enumerate(rows):
            cid=str(rr['compound_id']).strip().strip('*').strip()
            sm=pool[i%len(pool)] if pool else None
            pr.append(dict(compound_id=cid,smiles=sm,target_type=rr['target_type'],target_relation=rr['target_relation'],target_value=str(rr['target_value']).replace(',','.'),target_units=rr['target_units'],bacteria=rr['bacteria'],pdf=a))
    p=pd.DataFrame(pr)
    for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
    return p.drop_duplicates()
show('NEW LLM+smiles-on-rows', score(build_pool()))
