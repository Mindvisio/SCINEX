# hw_chemdb chem_db.csv -> ChemX benzimidazole pred.csv (single_agent format)
# Match gold's VERBATIM form: value_raw/unit_raw (not std), '=' relation, RDKit-canon smiles.
import argparse, re
import pandas as pd

def pdfname(s):
    s=str(s)
    if s.lower().endswith('.pdf'): s=s[:-4]
    return s.lower()

def cleanval(v):
    if pd.isna(v): return None
    s=str(v).strip().replace(',', '.')
    s=re.sub(r'^[<>=~\u2264\u2265\u2248]+','',s).strip()
    try: return '%g' % float(s)
    except: return s or None

def rel_of(*srcs):
    for s in srcs:
        if isinstance(s,str):
            if '>' in s or '\u2265' in s: return '>'
            if '<' in s or '\u2264' in s: return '<'
    return '='

def ttype(prop):
    if not isinstance(prop,str) or not prop.strip(): return None
    p=prop.strip()
    if p.lower()=='pmic': return 'pMIC'
    if 'mic' in p.lower(): return 'MIC'
    return p

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--keep', choices=['all','measurement'], default='all',
                    help='all=incl structure-only rows (smiles recall); measurement=rows with a value only')
    a=ap.parse_args()
    df=pd.read_csv(a.inp)
    rows=[]
    for _,r in df.iterrows():
        val=cleanval(r.get('value_raw'))
        if a.keep=='measurement' and val is None: continue
        rows.append(dict(
            compound_id=r.get('name_raw'),
            smiles=r.get('smiles_canonical'),
            target_type=ttype(r.get('property')),
            target_relation=rel_of(r.get('value_raw'), r.get('target_raw')),
            target_value=val,
            target_units=(r.get('unit_raw') if not pd.isna(r.get('unit_raw')) else None),
            bacteria=(r.get('organism_raw') if not pd.isna(r.get('organism_raw')) else None),
            pdf=pdfname(r.get('source_pdf')),
        ))
    out=pd.DataFrame(rows)
    for c in out.columns: out[c]=out[c].apply(lambda x: x if (x is not None and str(x)!='nan' and str(x)!='') else 'NOT_DETECTED')
    out=out.drop_duplicates()
    out.to_csv(a.out, index=False)
    print('wrote', a.out, out.shape, '| keep=%s'%a.keep)
    print('  non-ND smiles:', (out['smiles']!='NOT_DETECTED').sum(), '| non-ND value:', (out['target_value']!='NOT_DETECTED').sum())
    print('  units:', out['target_units'].value_counts().head(6).to_dict())
if __name__=='__main__': main()
