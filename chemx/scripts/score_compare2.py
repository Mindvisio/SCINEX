import sys, json, os
sys.path.insert(0,'/root/scinex/hw_chemdb')
import pandas as pd, metric_local as M
from rdkit import Chem; from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
TEXT6=['d2ra06667j','s41598-022-21435-6','s13065-018-0479-1','antibiotics10081002','acsomega.2c06142','antibiotics12071220']
cols=M.EXTRACTED_COLUMNS['benzimidazole']
gold=M.prepare_dataset('benzimidazole', M.NUMERIC_COLUMNS['benzimidazole'], M.SMILES_COLS['benzimidazole']); gold['pdf']=gold['pdf'].astype(str).str.lower()
MU=lambda s: str(s).replace(chr(0x3bc),chr(0xb5)).replace(chr(0x39c),chr(0xb5))
for _c in cols: gold[_c]=gold[_c].apply(MU)
def canon(s):
    try: mm=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(mm) if mm else None
    except: return None
def clean_id(x):
    return str(x).strip().strip('*').strip().strip('()').strip().strip('*').strip()
db=pd.read_csv('/tmp/chemx_benz/chem_db.dedup.csv'); db['pdfn']=db['source_pdf'].astype(str).str.lower().str.replace('.pdf','',regex=False)
ocsr={a:[s for s in (canon(x) for x in db[db['pdfn']==a]['smiles_canonical'].dropna().unique()) if s] for a in TEXT6}
def build(prefix):
    pr=[]
    for a in TEXT6:
        f='/tmp/chemx_benz/llm_%s_%s.json'%(prefix,a); rows=json.load(open(f)) if os.path.exists(f) else []
        pool=ocsr.get(a,[])
        for i,r in enumerate(rows):
            pr.append(dict(compound_id=clean_id(r['compound_id']),smiles=(pool[i%len(pool)] if pool else None),target_type=r['target_type'],target_relation=r['target_relation'],target_value=str(r['target_value']).replace(',','.'),target_units=r['target_units'],bacteria=r['bacteria'],pdf=a))
    p=pd.DataFrame(pr)
    if len(p):
        for c in p.columns: p[c]=p[c].apply(lambda x: x if (x is not None and str(x) not in ('nan','','None')) else 'NOT_DETECTED')
        p=p.drop_duplicates()
        for _c in cols: p[_c]=p[_c].apply(MU)
    return p
def ppf1(p,a):
    pA=p[p['pdf']==a][cols] if len(p) else pd.DataFrame(columns=cols)
    return M.calc_metrics(gold[gold['pdf']==a][cols], pA)['f1'].mean()
def macro(p,arts):
    m=M.empty_metrics(cols)
    for a in arts: m+=M.calc_metrics(gold[gold['pdf']==a][cols], (p[p['pdf']==a][cols] if len(p) else pd.DataFrame(columns=cols)))
    return (m/len(arts))['f1'].mean()
mp=build('mpgem'); tb=build('tabula')
print('%-22s %6s %6s'%('paper','mpgem','tabula'))
for a in TEXT6: print('%-22s %.3f  %.3f'%(a, ppf1(mp,a), ppf1(tb,a)))
c5=[a for a in TEXT6 if a!='antibiotics10081002']
print()
print('MACRO 6 text papers:            mpgem=%.4f  tabula=%.4f'%(macro(mp,TEXT6), macro(tb,TEXT6)))
print('MACRO common-5 (no antib10081002): mpgem=%.4f  tabula=%.4f'%(macro(mp,c5), macro(tb,c5)))
