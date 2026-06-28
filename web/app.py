import hashlib, re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
import pandas as pd
try:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
    _RD = True
except Exception:
    _RD = False

ROOT = Path(__file__).resolve().parent.parent
WEB  = Path(__file__).resolve().parent
FRONT = WEB / 'scinex_front.html'
BENZ_PRED = ROOT / 'chemx' / 'results' / 'benz_pred_final.csv'
app = FastAPI(title='scinex')

def _s(v):
    if v is None: return None
    try:
        if isinstance(v, float) and pd.isna(v): return None
    except Exception: pass
    t = str(v).strip()
    return None if t in ('','nan','None','NaN','<NA>') else t

def _num(v):
    try: return float(v)
    except Exception: return v

_SVG = {}
def _svg(smiles):
    if not _RD or not smiles: return None
    if smiles in _SVG: return _SVG[smiles]
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        _SVG[smiles] = None; return None
    d = rdMolDraw2D.MolDraw2DSVG(240, 170)
    rdMolDraw2D.PrepareAndDrawMolecule(d, m)
    d.FinishDrawing()
    s = d.GetDrawingText()
    s = s[s.find('<svg'):]
    _SVG[smiles] = s
    return s

def _canon(smiles):
    if not _RD or not smiles: return smiles
    m = Chem.MolFromSmiles(smiles)
    return Chem.MolToSmiles(m) if m else None

_STRAIN = re.compile(r'\b(ATCC|ATTC|NCTC|NCIMB|DSM|MTCC|KCTC|CCM|CIP|NRRL|MRSA|VRE|H37Rv|PAO1|O157)\b.*', re.I)
def _split_org(org):
    o = _s(org)
    if not o: return None, None
    m = _STRAIN.search(o)
    if m:
        return (o[:m.start()].strip(' ,;') or o), o[m.start():].strip()
    return o, None

def _cell(value, raw, dtype, prov, unit=None, conf=None, svg=None):
    c = {'value': value, 'raw': raw, 'dtype': dtype, 'provenance': [prov] if prov else []}
    if unit: c['unit'] = unit
    if conf is not None: c['confidence'] = conf
    if svg is not None: c['svg'] = svg
    return c

def _ptable(pdf, cid, col):
    return {'doc_id': pdf, 'page': None, 'modality': 'table', 'locator': {'kind':'table_cell','row':cid,'col':col}, 'snippet':'', 'extractor':'table-llm'}
def _pfig(pdf, cid):
    return {'doc_id': pdf, 'page': None, 'modality': 'image', 'locator': {'kind':'figure_label','label':cid}, 'snippet':'', 'extractor':'ocsr'}

def benz_rows():
    if not BENZ_PRED.exists(): return [], []
    df = pd.read_csv(BENZ_PRED)
    df = df[df['target_units'].astype(str).str.upper() != 'NOT_DETECTED'].copy()
    df['_n'] = df.groupby(['pdf','compound_id'])['smiles'].transform('nunique')
    rows = []
    for i, r in df.iterrows():
        pdf = _s(r.get('pdf')) or 'doc'
        cid = _s(r.get('compound_id')) or '?'
        reliable = int(r.get('_n', 99)) == 1
        cells = {}
        cells['compound_id'] = _cell(cid, cid, 'id', _ptable(pdf, cid, 'compound_id'))
        if reliable:
            smi = _canon(_s(r.get('smiles')))
            if smi:
                cells['smiles'] = _cell(smi, smi, 'smiles', _pfig(pdf, cid), conf=0.9, svg=_svg(smi))
        val = _s(r.get('target_value')); unit = _s(r.get('target_units')) or ''
        rel = _s(r.get('target_relation')) or '='
        if val is not None:
            num = _num(val)
            if rel == '=' and isinstance(num, float):
                cval = num; raw = (val + ' ' + unit).strip()
            else:
                cval = (rel + ' ' + val + ' ' + unit).strip(); raw = cval
            cells['mic'] = _cell(cval, raw, 'quantity', _ptable(pdf, cid, 'mic'), unit=unit, conf=0.85)
        org, strain = _split_org(r.get('bacteria'))
        if org: cells['organism'] = _cell(org, org, 'enum', _ptable(pdf, cid, 'organism'), conf=0.85)
        if strain: cells['strain'] = _cell(strain, strain, 'string', _ptable(pdf, cid, 'strain'))
        cells['assay'] = _cell('MIC', 'MIC', 'string', _ptable(pdf, cid, 'assay'))
        row = {'id': f'{cid}@{pdf}#{i}', 'label': cid, 'page': None, 'cells': cells}
        if 'smiles' not in cells: row['structure_unresolved'] = True
        rows.append(row)
    docs = sorted({(_s(r.get('pdf')) or 'doc') for _, r in df.iterrows()})
    return rows, [{'doc_id': d, 'title': d} for d in docs]

DOMAIN_SRC = {'Benzimidazoles': benz_rows}

@app.get('/')
def index(): return FileResponse(str(FRONT))

@app.get('/api/health')
def health(): return {'status':'ok','rdkit':_RD,'benz_pred':BENZ_PRED.exists(),'front':FRONT.exists()}

@app.post('/api/chemx/extract')
async def extract(file: UploadFile | None = File(None), domain: str = Form('Benzimidazoles')):
    raw = await file.read() if file is not None else b''
    h = hashlib.sha1(raw).hexdigest()[:12] if raw else 'nofile'
    src = DOMAIN_SRC.get(domain)
    if src is None:
        return JSONResponse({'extraction_id':f'ext_{h}','domain':domain,'documents':[],'rows':[],'metrics':None,'note':f"domain '{domain}' not wired yet (benchmark-real: Benzimidazoles)"})
    rows, documents = src()
    n_struct = sum(1 for x in rows if 'smiles' in x['cells'])
    return {'extraction_id':f'ext_{h}','domain':domain,'documents':documents,'rows':rows,'metrics':None,'stats':{'rows':len(rows),'with_structure':n_struct}}
