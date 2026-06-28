# -*- coding: utf-8 -*-
"""Canonical benzimidazole pred builder -> official metric path. Run:
  python chemx/scripts/build_benz_pred.py   # writes /tmp/benz_pred.csv
  python hw_chemdb/metric_local.py --dataset benzimidazole --source single_agent --pred /tmp/benz_pred.csv
Divides by ALL open-access articles (9), not the locally-available PDFs (7). Uses norm_number via assemble."""
import sys,json,os
_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0,_ROOT); sys.path.insert(0,os.path.join(_ROOT,'hw_chemdb'))
import pandas as pd
from chemx.smiles_router import ocsr_ensemble_pool
from chemx.assemble import assemble_pred
HAVE7=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
CORE='c1ccc2ncnc2c1'; RES=os.path.join(_ROOT,'chemx','results'); _LLM=os.environ.get('SCINEX_BENZ_LLM_DIR', RES)
def em(a): f=RES+'/enriched_'+a+'.json'; return json.load(open(f)) if os.path.exists(f) else {}
preds=[]
for a in HAVE7:
    _f='%s/llm_%s.json'%(_LLM,a); rows=json.load(open(_f)) if os.path.exists(_f) else []
    preds.append(assemble_pred(a,'benzimidazole',rows,assign_map=em(a),pool=ocsr_ensemble_pool(RES,a,CORE)))
pred=pd.concat(preds,ignore_index=True)
cols=['compound_id','smiles','target_type','target_relation','target_value','target_units','bacteria','pdf']
pred[cols].to_csv('/tmp/benz_pred.csv', index=False)
print('wrote /tmp/benz_pred.csv rows=%d papers=%d'%(len(pred), pred['pdf'].nunique()))
