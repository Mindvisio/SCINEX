"""scinex production smiles router.

Picks the right smiles-extraction strategy per paper, then combines sources via union_clean.
Runs in .venv-lite (has llm_clients, rdkit, py2opsin). OCSR engine pools are produced by
separate stage scripts (MolScribe/.venv-chem, DECIMER/.venv-decimer, Gemini via llm_clients)
and merged here. See ROUTER.md for the model-routing rationale.
"""
import os, re, json, glob
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')

# Primary ORCHESTRATOR model for TEXT reasoning (strategy classify, IUPAC-name extraction, row/
# R-table extraction). DeepSeek-V4-Pro via the DIRECT api.deepseek.com route -- NO OpenRouter, NO
# proxy. Validated at parity with claude-opus on IUPAC extraction (acsomega 7/7 == 7/7, ~18s vs 14s)
# and far cheaper. Vision/figure OCSR stays on claude-opus (smiles_claude_vision), where it dominates.
# Override with SCINEX_ORCH_MODEL.
ORCH_MODEL = os.environ.get('SCINEX_ORCH_MODEL', 'deepseek-direct')

def canon(s):
    try:
        m = Chem.MolFromSmiles(str(s).strip()); return Chem.MolToSmiles(m) if m else None
    except Exception: return None

def _complete(s, core):
    m = Chem.MolFromSmiles(s)
    if m is None or any(a.GetAtomicNum() == 0 for a in m.GetAtoms()) or len(Chem.GetMolFrags(m)) != 1:
        return False
    n = m.GetNumHeavyAtoms()
    return 10 <= n <= 80 and (core is None or m.HasSubstructMatch(core))

# ---------------- Level 1: strategy classification ----------------
_IUPAC_RE = re.compile(r'\b(\d-|\(\d?[RS]\)|oxo|yl\)?methyl|carboxamide|carbamate|sulfonyl|'
                       r'benzo\[d\]imidazol|oxazolidin|tetrahydro|dihydro|pyrazol)', re.I)

def classify_strategy(ocr_text, name_col_values=None):
    """Cheap rule-based router. Optionally confirm with DeepSeek (call_json) for ambiguous cases.
    Returns one of: 'opsin' | 'pubchem' | 'ocsr'."""
    # trivial named drugs present (cocrystals/complexes style) -> PubChem
    if name_col_values:
        named = [n for n in name_col_values if str(n) not in ('', 'NOT_DETECTED', 'nan')]
        if named and sum(1 for n in named if ' ' not in str(n).strip() or str(n)[0].isupper()) >= max(3, len(named)//2):
            return 'pubchem'
    # density of systematic-name tokens in the experimental section -> OPSIN
    hits = len(_IUPAC_RE.findall(ocr_text or ''))
    if hits >= 15:
        return 'opsin'
    return 'ocsr'

# ---------------- Level 2: per-strategy extractors ----------------
def smiles_opsin(ocr_text, model=None):
    """IUPAC names -> OPSIN. Deterministic/exact. Best where names are explicit (oxazolidinone)."""
    model = model or ORCH_MODEL
    from typing import List
    from pydantic import BaseModel, Field
    from lib.llm_clients import call_json
    from py2opsin import py2opsin
    class Cmp(BaseModel):
        compound_id: str = Field(description='label e.g. 11a, 3b')
        iupac_name: str = Field(description='clean systematic IUPAC name, OPSIN-parseable')
    class Names(BaseModel):
        compounds: List[Cmp]
    SYS = ('Return, for each final labelled target compound, its full systematic IUPAC name as an '
           'OPSIN parser accepts. Strip markdown. Keep (R)/(S). Only final compounds, not intermediates.')
    sr = call_json(model, 'Extract {compound_id, iupac_name} for every final compound:\n\n' + ocr_text[:75000],
                   Names, system_prompt=SYS, max_tokens=8000, reasoning_effort='low', timeout=290)
    out = {}
    for c in sr.parsed.compounds:
        cs = canon(py2opsin(c.iupac_name) or '')
        if cs: out[c.compound_id.strip()] = cs
    return out

def smiles_pubchem(name_map, cache_path='/tmp/pubchem_cache.json'):
    """Trivial drug name -> PubChem IsomericSMILES. For cocrystals/complexes.
    name_map: {compound_id: drug_name}. Returns {compound_id: smiles}."""
    import urllib.parse, urllib.request, time
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    def pubchem(name):
        name = str(name).strip()
        if not name or name == 'NOT_DETECTED': return None
        if name in cache: return cache[name]
        res = None
        for prop in ('IsomericSMILES', 'CanonicalSMILES'):
            try:
                u = ('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s/property/%s/TXT'
                     % (urllib.parse.quote(name), prop))
                r = urllib.request.urlopen(u, timeout=20).read().decode().strip().split('\n')[0]
                if r and 'Status' not in r and 'Fault' not in r:
                    res = canon(r); break
            except Exception: pass
        cache[name] = res; time.sleep(0.22); return res
    out = {cid: pubchem(nm) for cid, nm in name_map.items()}
    json.dump(cache, open(cache_path, 'w'))
    return {k: v for k, v in out.items() if v}

def ocsr_ensemble_pool(results_dir, paper, core_smarts):
    """Merge complete-core structures from all OCSR engines into one deduped pool.
    SINGLE source of truth: ocsr_pool_<paper>.json with engines={molscribe,decimer,claude_vision}
    (+ legacy top-level `pool`=MolScribe, + flat per-engine files as fallback for robustness against
    a parallel regen of ocsr_pool). Gemini intentionally excluded (0 marginal gold + dilutes precision).
    -> list[canonical smiles]."""
    core = Chem.MolFromSmarts(core_smarts) if core_smarts else None
    pool = set()
    def _add(items):
        for x in (items or []):
            s = (x.get('smiles') or x.get('canon')) if isinstance(x, dict) else x
            c = canon(s)
            if c:
                pool.add(c)
    # unified file (preferred convention)
    uf = f'{results_dir}/ocsr_pool_{paper}.json'
    if os.path.exists(uf):
        d = json.load(open(uf))
        eng = d.get('engines') or {}
        for lst in eng.values():
            _add(lst)
        if not eng:                       # legacy ocsr_pool: top-level pool == MolScribe full-page
            _add(d.get('pool'))
    # flat per-engine files (fallback / supplement)
    for fn in ('molscribe_%s.json', 'figpool_%s.json', 'decimer_raw_%s.json', 'claudepg_%s.json'):
        f = f'{results_dir}/' + (fn % paper)
        if os.path.exists(f):
            _add(json.load(open(f)))
    return [s for s in pool if _complete(s, core)]

# ---------------- Level 3: combine ----------------
def union_clean(enrichment, pools, core_smarts):
    """Final smiles candidate set = enrichment (OPSIN/PubChem/R-enum) UNION complete-core OCSR pool.
    enrichment: list[smiles]; pools: list[smiles] (already merged). Dedup, enrichment-first."""
    core = Chem.MolFromSmarts(core_smarts) if core_smarts else None
    enr = [c for c in (canon(s) for s in (enrichment or [])) if c]
    cpool = [s for s in dict.fromkeys(canon(p) for p in (pools or []) if canon(p)) if _complete(s, core)]
    return list(dict.fromkeys(enr + cpool))

# ---------------- top-level router ----------------
def resolve_paper(paper, ocr_text, *, results_dir, core_smarts, pdf_path=None,
                  name_map=None, name_col_values=None):
    """Return (strategy, {compound_id: smiles_or_None}, candidate_pool).
    candidate_pool is the deduped union_clean list usable for the multiset smiles column."""
    strat = classify_strategy(ocr_text, name_col_values)
    per_cid, enrichment = {}, []
    if strat == 'opsin':
        per_cid = smiles_opsin(ocr_text); enrichment = list(per_cid.values())
    elif strat == 'pubchem' and name_map:
        per_cid = smiles_pubchem(name_map); enrichment = list(per_cid.values())
    pools = ocsr_ensemble_pool(results_dir, paper, core_smarts)
    cand = union_clean(enrichment, pools, core_smarts)
    return strat, per_cid, cand


def smiles_claude_vision(page_images, model='claude-opus', batch=3, core_smarts=None, max_tokens=4000):
    """PRIMARY vision/figure OCSR. Reads rendered pages with a strong multimodal LLM (claude-opus),
    expanding R-table/Markush per labelled variant -- empirically dominates MolScribe/DECIMER/Gemini
    (antibiotics 26/57 vs <=3; intechopen 2/4 vs 0). Returns complete-core canonical SMILES pool.
    page_images: list of PNG paths (rasterize vector->raster upstream)."""
    from lib.llm_clients import call_vision
    core = Chem.MolFromSmarts(core_smarts) if core_smarts else None
    SYS = ('Expert OCSR. Identify EVERY distinct chemical structure on these pages (expand any '
           'R-table/Markush into one entry per labelled variant). Output ONLY a JSON array of '
           '{"label":"","smiles":""}. No prose, no fences.')
    pool = set()
    for i in range(0, len(page_images), batch):
        chunk = page_images[i:i+batch]
        try:
            r = call_vision(model, 'Extract all chemical structures as JSON array.', chunk,
                            system_prompt=SYS, max_tokens=max_tokens, reasoning_effort='low', timeout=220)
            txt = r.text.strip().replace('```json', '').replace('```', '').strip()
            try: arr = json.loads(txt)
            except Exception: arr = []
            for o in (arr or []):
                cs = canon(o.get('smiles'))
                if cs and _complete(cs, core):
                    pool.add(cs)
        except Exception:
            continue
    return list(pool)


def normalize_pred(df, domain):
    """Apply the parallel normalization track (chemx/scripts/normalize.py) to an assembled pred:
    domain-aware micro-sign on target_units + safe full-row dedup. Normalization measurably helped
    (units micro-sign is DOMAIN-dependent: benz U+00B5, oxa/nanozymes U+03BC; the global MU was a mine)."""
    import sys as _sys
    if '/root/scinex/chemx/scripts' not in _sys.path:
        _sys.path.insert(0, '/root/scinex/chemx/scripts')
    import normalize as _nz
    if 'target_units' in df.columns:
        df = df.copy()
        df['target_units'] = df['target_units'].map(
            lambda u: _nz.micro_norm(str(u), domain) if u not in (None, '', 'NOT_DETECTED') else u)
    return _nz.dedup_objects(df)
