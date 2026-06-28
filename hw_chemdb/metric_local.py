# Faithful local copy of ChemX/LLM/src/metric_calc.py: gold from local CSV (no HF),
# + optional --pred override and --articles subset. calc_metrics/preprocessing verbatim.
import os, sys, argparse
import pandas as pd, numpy as np
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from chemx_constants import DATASETS, EXTRACTED_COLUMNS, NUMERIC_COLUMNS, SMILES_COLS
except ImportError:
    sys.path.insert(0, os.environ.get('CHEMX_SRC', '/tmp/ChemX/LLM/src'))
    from constants import DATASETS, EXTRACTED_COLUMNS, NUMERIC_COLUMNS, SMILES_COLS

BASE='/tmp/ChemX/LLM'
_GOLD_DIR = os.environ.get('CHEMX_GOLD_DIR') or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'chemx', 'data', 'gold')
GOLD={'benzimidazole':'Benzimidazoles.csv','oxazolidinone':'Oxazolidinones.csv','cocrystals':'Co-crystals.csv','complexes':'Complexes.csv','nanozymes':'Nanozymes.csv','magnetic':'Nanomag.csv','cytotoxicity':'Cytotox.csv','seltox':'SelTox.csv','synergy':'Synergy.csv'}

def convert_comma(x):
    try: return str(x.replace(',', '.'))
    except: return str(x)
def select_open_access(df): return df.loc[df['access'] == 1]

def prepare_dataset(dataset, n_cols, s_cols):
    df = pd.read_csv(os.path.join(_GOLD_DIR, GOLD[dataset]))   # repo-relative gold (override: CHEMX_GOLD_DIR)
    for col in n_cols: df[col] = df[col].apply(convert_comma)
    if dataset in ['oxazolidinone','benzimidazole']:
        df.target_relation = df.target_relation.apply(lambda x: '=' if x == "'='" else x)
    df = df.fillna('NOT_DETECTED')
    if dataset in ['oxazolidinone','benzimidazole','cocrystals','complexes']:
        for col in s_cols:
            df[col] = df[col].apply(lambda x: Chem.MolToSmiles(Chem.MolFromSmiles(x)) if Chem.MolFromSmiles(x) is not None else x)
    return select_open_access(df)

def prepare_result(dataset, source, cols, s_cols, pred_path=None):
    if source == 'single_agent':
        p = pred_path or os.path.join(BASE, f'result/from_single_agent/{dataset}/pred.csv')
        df = pd.read_csv(p)
        if dataset in ['cytotoxicity','seltox','synergy','magnetic']:
            df['pdf'] = df['pdf'].apply(lambda x: str(x) + '.pdf')
        return df.drop_duplicates()
    if source == 'pdf':
        df_output = pd.read_csv(os.path.join(BASE, f'result/from_pdf/{dataset}_result.csv'))
    elif source == 'image':
        df_output = pd.read_csv(os.path.join(BASE, f'result/from_image/{dataset}_result.csv'), sep='\t')
    import json
    rows=[]
    for pdf in df_output['pdf']:
        rj = json.loads(df_output['output'][df_output['pdf'] == pdf].item())
        for s in rj['samples']:
            row = {k: v for k, v in zip(cols, [s.get(c) for c in cols])}
            row['pdf'] = pdf + '.pdf' if dataset in ['cytotoxicity','seltox','synergy','magnetic'] else pdf
            rows.append(row)
    df = pd.DataFrame(rows)
    if dataset in ['oxazolidinone','benzimidazole','cocrystals','complexes']:
        for col in s_cols:
            df[col] = df[col].apply(lambda x: Chem.MolToSmiles(Chem.MolFromSmiles(x)) if Chem.MolFromSmiles(x) is not None else x)
    if source == 'pdf': df['pdf'] = df['pdf'].apply(lambda x: x[:-4])
    elif source == 'image': df['pdf'] = df['pdf'].apply(lambda x: x.split('\\')[-1])
    return df.drop_duplicates()

def calc_metrics(df_true, df_pred):
    from copy import deepcopy
    metrics={}
    for col in df_true.columns:
        tvs=list(df_true[col].astype(str).values); pvs=list(df_pred[col].astype(str).values)
        pv=deepcopy(pvs); tp=0
        for v in deepcopy(tvs):
            if v in pv: pv.pop(pv.index(v)); tp+=1
        tv=deepcopy(tvs); pv=deepcopy(pvs); fp=0
        for v in pv:
            if v in tv: tv.pop(tv.index(v))
            else: fp+=1
        tv=deepcopy(tvs); pv=deepcopy(pvs); fn=0
        for v in tv:
            if v in pv: pv.pop(pv.index(v))
            else: fn+=1
        precision=tp/(tp+fp) if (tp+fp)>0 else 0.0
        recall=tp/(tp+fn) if (tp+fn)>0 else 0.0
        f1=2*precision*recall/(precision+recall) if (precision+recall)>0 else 0.0
        metrics[col]={'tp':tp,'fp':fp,'fn':fn,'precision':precision,'recall':recall,'f1':f1}
    return pd.DataFrame(metrics).T

def empty_metrics(cols):
    return pd.DataFrame({c:{'tp':0,'fp':0,'fn':0,'precision':0,'recall':0,'f1':0} for c in cols}).T

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dataset', required=True, choices=DATASETS)
    ap.add_argument('--source', default='single_agent', choices=['image','pdf','single_agent'])
    ap.add_argument('--pred', default=None, help='override pred csv (single_agent)')
    ap.add_argument('--articles', default=None, help='comma-list of pdf names to restrict eval')
    a=ap.parse_args()
    ds=a.dataset; cols=EXTRACTED_COLUMNS[ds]; n_cols=NUMERIC_COLUMNS[ds]; s_cols=SMILES_COLS[ds]
    df_d=prepare_dataset(ds, n_cols, s_cols)
    df_r=prepare_result(ds, a.source, cols, s_cols, a.pred)
    df_d['pdf']=df_d['pdf'].apply(lambda x: str(x).lower())
    df_r['pdf']=df_r['pdf'].apply(lambda x: str(x).lower())
    arts=list(df_d['pdf'].unique())
    if a.articles:
        keep=set(s.strip().lower() for s in a.articles.split(','))
        arts=[x for x in arts if x in keep]
    m=empty_metrics(cols)
    print(f'Analyze {len(arts)} articles: {sorted(arts)}')
    for art in arts:
        m += calc_metrics(df_d.loc[df_d['pdf']==art][cols], df_r.loc[df_r['pdf']==art][cols])
    m = m/len(arts)
    pd.set_option('display.width',200); pd.set_option('display.max_columns',10)
    print(m.round(4))
    print('MACRO-F1: %.4f' % m['f1'].mean())

if __name__=='__main__': main()
