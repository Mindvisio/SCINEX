import sys, json, os
sys.path.insert(0,'/root/scinex/hw_chemdb')
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
HAVE7=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
cols=M.EXTRACTED_COLUMNS['benzimidazole']
gold=M.prepare_dataset('benzimidazole', M.NUMERIC_COLUMNS['benzimidazole'], M.SMILES_COLS['benzimidazole']); gold['pdf']=gold['pdf'].astype(str).str.lower()
allOA=sorted(gold['pdf'].unique())
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else None
    except: return None
def cid(x): return str(x).strip().strip('*').strip().strip('()').strip().strip('*').strip()
db=pd.read_csv('/tmp/chemx_benz/chem_db.dedup.csv'); db['pdfn']=db['source_pdf'].astype(str).str.lower().str.replace('.pdf','',regex=False)
ocsr={a:[s for s in (canon(x) for x in db[db['pdfn']==a]['smiles_canonical'].dropna().unique()) if s] for a in HAVE7}
RES='/root/scinex/chemx/results'
enr={}
for a in HAVE7:
    f='%s/enriched_%s.json'%(RES,a)
    enr[a]=list(dict.fromkeys([canon(v) for v in json.load(open(f)).values() if canon(v)])) if os.path.exists(f) else []
def build(mode):
    pr=[]
    for a in HAVE7:
        rows=json.load(open('/tmp/chemx_benz/llm_%s.json'%a)) if os.path.exists('/tmp/chemx_benz/llm_%s.json'%a) else []
        pool=ocsr.get(a,[]); el=enr.get(a,[])
        if mode=='pool': cand=pool
        elif mode=='union': cand=list(dict.fromkeys(el+pool))
        elif mode=='enrich_first_only': cand=list(dict.fromkeys(el)) if el else pool
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
for mode in ['pool','union']:
    p=build(mode)
    for scope,arts in [('/7',HAVE7),('/allOA',allOA)]:
        f=macro(p,arts); print('%-6s %-7s MACRO=%.4f smiles=%.3f val=%.3f units=%.3f bact=%.3f'%(mode,scope,f.mean(),f['smiles'],f['target_value'],f['target_units'],f['bacteria']))
print('--- per-article smiles F1 (pool -> union) ---')
pp=build('pool'); pu=build('union')
for a in HAVE7:
    fb=M.calc_metrics(gold[gold['pdf']==a][cols], pp[pp['pdf']==a][cols])['f1']['smiles']
    fa=M.calc_metrics(gold[gold['pdf']==a][cols], pu[pu['pdf']==a][cols])['f1']['smiles']
    print('  %-26s %.3f -> %.3f %s'%(a,fb,fa,'<<' if abs(fa-fb)>1e-6 else ''))
