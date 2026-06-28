import sys,json,os
_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0,_ROOT); sys.path.insert(0,os.path.join(_ROOT,'hw_chemdb'))
import pandas as pd
from chemx.smiles_router import ocsr_ensemble_pool
from chemx.assemble import assemble_pred
HAVE7=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
NEW=['rjc.2023.1638382','2023.12.si5a.0471']
ALL9=HAVE7+NEW
CORE='c1ccc2ncnc2c1'; RES=os.path.join(_ROOT,'chemx','results'); _LLM=os.environ.get('SCINEX_BENZ_LLM_DIR', RES)
def em(a):
    f=RES+'/enriched_'+a+'.json'; return json.load(open(f)) if os.path.exists(f) else {}
def pool(a):
    try: return ocsr_ensemble_pool(RES,a,CORE)
    except Exception: return []
preds=[]
for a in ALL9:
    p='%s/llm_%s.json'%(_LLM,a)
    rows=json.load(open(p)) if os.path.exists(p) else []
    preds.append(assemble_pred(a,'benzimidazole',rows,assign_map=em(a),pool=pool(a)))
pred=pd.concat(preds,ignore_index=True)
cols=['compound_id','smiles','target_type','target_relation','target_value','target_units','bacteria','pdf']
pred[cols].to_csv('/tmp/benz_pred9.csv', index=False)
print('wrote rows=%d papers=%d (new: rjc=%d ecb=%d)'%(len(pred), pred['pdf'].nunique(), (pred['pdf']=='rjc.2023.1638382').sum(), (pred['pdf']=='2023.12.si5a.0471').sum()))
