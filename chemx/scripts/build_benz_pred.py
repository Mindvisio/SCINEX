# -*- coding: utf-8 -*-
"""Canonical benzimidazole pred builder -> official metric path. Run:
  python chemx/scripts/build_benz_pred.py   # writes /tmp/benz_pred.csv
  python hw_chemdb/metric_local.py --dataset benzimidazole --source single_agent --pred /tmp/benz_pred.csv
Divides by ALL open-access articles (9), not the locally-available PDFs (7). Uses norm_number via assemble."""
import sys,json,os
sys.path.insert(0,'/root/scinex'); sys.path.insert(0,'/root/scinex/hw_chemdb')
import pandas as pd
from chemx.smiles_router import ocsr_ensemble_pool
from chemx.assemble import assemble_pred
HAVE7=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
CORE='c1ccc2ncnc2c1'; RES='/root/scinex/chemx/results'
def em(a): f=RES+'/enriched_'+a+'.json'; return json.load(open(f)) if os.path.exists(f) else {}
preds=[]
for a in HAVE7:
    rows=json.load(open('/tmp/chemx_benz/llm_%s.json'%a)) if os.path.exists('/tmp/chemx_benz/llm_%s.json'%a) else []
    preds.append(assemble_pred(a,'benzimidazole',rows,assign_map=em(a),pool=ocsr_ensemble_pool(RES,a,CORE)))
pred=pd.concat(preds,ignore_index=True)
cols=['compound_id','smiles','target_type','target_relation','target_value','target_units','bacteria','pdf']
pred[cols].to_csv('/tmp/benz_pred.csv', index=False)
print('wrote /tmp/benz_pred.csv rows=%d papers=%d'%(len(pred), pred['pdf'].nunique()))
