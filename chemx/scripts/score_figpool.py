import sys, json, os
sys.path.insert(0,'/root/scinex/hw_chemdb')
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
HAVE7=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
cols=M.EXTRACTED_COLUMNS['benzimidazole']
gold=M.prepare_dataset('benzimidazole', M.NUMERIC_COLUMNS['benzimidazole'], M.SMILES_COLS['benzimidazole']); gold['pdf']=gold['pdf'].astype(str).str.lower()
allOA=sorted(gold['pdf'].unique())
BZI=Chem.MolFromSmarts('c1ccc2ncnc2c1')
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else None
    except: return None
def cid(x): return str(x).strip().strip('*').strip().strip('()').strip().strip('*').strip()
def complete(s):
    m=Chem.MolFromSmiles(s)
    if m is None: return False
    if any(a.GetAtomicNum()==0 for a in m.GetAtoms()): return False
    if len(Chem.GetMolFrags(m))!=1: return False
    n=m.GetNumHeavyAtoms()
    if n<12 or n>60: return False
    return m.HasSubstructMatch(BZI)
db=pd.read_csv('/tmp/chemx_benz/chem_db.dedup.csv'); db['pdfn']=db['source_pdf'].astype(str).str.lower().str.replace('.pdf','',regex=False)
ocsr={a:[s for s in (canon(x) for x in db[db['pdfn']==a]['smiles_canonical'].dropna().unique()) if s] for a in HAVE7}
RES='/root/scinex/chemx/results'
enr={a:(list(dict.fromkeys([canon(v) for v in json.load(open('%s/enriched_%s.json'%(RES,a))).values() if canon(v)])) if os.path.exists('%s/enriched_%s.json'%(RES,a)) else []) for a in HAVE7}
def build(mode):
    pr=[]
    for a in HAVE7:
        rows=json.load(open('/tmp/chemx_benz/llm_%s.json'%a)) if os.path.exists('/tmp/chemx_benz/llm_%s.json'%a) else []
        pool=ocsr.get(a,[]); el=enr.get(a,[]); cpool=[s for s in pool if complete(s)]
        if mode=='pool': cand=pool
        elif mode=='union': cand=list(dict.fromkeys(el+pool))
        elif mode=='union_clean': cand=list(dict.fromkeys(el+cpool)) or pool
        for i,r in enumerate(rows):
            sm=cand[i%len(cand)] if cand else None
            pr.append(dict(compound_id=cid(r['compound_id']),smiles=sm,target_type=r['target_type'],target_relation=r['target_relation'],target_value=str(r['target_value']).replace(',','.'),target_units=r['target_units'],bacteria=r['bacteria'],pdf=a))
    p=pd.DataFrame(pr)
    for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
    return p.drop_duplicates()
def macro(p,arts):
    m=M.empty_metrics(cols)
    for a in arts: m+=M.calc_metrics(gold[gold['pdf']==a][cols], (p[p['pdf']==a][cols] if len(p) else pd.DataFrame(columns=cols)))
    return (m/len(arts))['f1']
for mode in ['pool','union','union_clean']:
    p=build(mode)
    f=macro(p,HAVE7); fo=macro(p,allOA)
    print('%-12s /7 MACRO=%.4f smiles=%.3f | /allOA MACRO=%.4f smiles=%.3f'%(mode,f.mean(),f['smiles'],fo.mean(),fo['smiles']))
print('--- per-article smiles (pool->union->union_clean) ---')
pp,pu,pc=build('pool'),build('union'),build('union_clean')
for a in HAVE7:
    f1=M.calc_metrics(gold[gold['pdf']==a][cols], pp[pp['pdf']==a][cols])['f1']['smiles']
    f2=M.calc_metrics(gold[gold['pdf']==a][cols], pu[pu['pdf']==a][cols])['f1']['smiles']
    f3=M.calc_metrics(gold[gold['pdf']==a][cols], pc[pc['pdf']==a][cols])['f1']['smiles']
    print('  %-26s %.3f -> %.3f -> %.3f'%(a,f1,f2,f3))
