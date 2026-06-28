"""scinex extraction orchestrator -- a decision graph over the tools we have.

Flow (each node logs {node, decision, why, evidence} into a trace = the reasoning graph):

  N0 detect_doc_type      pdf | web(stub)
  N1 classify_pdf         scanned vs digital ; embedded-figure count ; vector-drawing flag
  N2 ingest_text          ocr.dispatch -> pymupdf | Mathpix | Mistral(+conf gate)
  N3 prepare_figures      vector->raster: rasterize pages for OCSR (universal) + keep embedded crops
  N4 classify_strategy    OPSIN | PubChem | OCSR   (+ OCR<->strategy coupling gate)
  N5 run_strategy         OPSIN names / PubChem / OCSR-ensemble(MolScribe u DECIMER u Gemini)
  N6 coref                OpenChemIE structure<->label  (assign SMILES to compound_id)  [3080]
  N7 gates                confidence + completeness -> review flags

Reactions are intentionally OUT (added later, in the platform). OCSR engine RUNS happen on the 3080;
this driver executes the decision layer + sci-node-reachable stages, and reuses cached engine pools
when present (fresh runs subprocess to the 3080 -- see _ocsr_pool hook).
"""
from __future__ import annotations
import os, sys, json, time, subprocess
from pathlib import Path
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
import pymupdf
from chemx.smiles_router import (classify_strategy, smiles_opsin, smiles_pubchem,
                                 ocsr_ensemble_pool, union_clean, canon)

DIGITAL_MIN_CHARS_PER_PAGE = 100
RASTER_DPI = 300


class Trace:
    def __init__(self): self.nodes = []
    def log(self, node, decision, why, **evidence):
        self.nodes.append({'node': node, 'decision': decision, 'why': why, 'evidence': evidence})
        print('  [%s] %s -- %s%s' % (node, decision, why,
              (' | ' + ', '.join('%s=%s' % (k, v) for k, v in evidence.items())) if evidence else ''),
              flush=True)
    def dump(self): return self.nodes


# ---------- N0 ----------
def detect_doc_type(path, tr):
    ext = Path(path).suffix.lower()
    dt = 'pdf' if ext == '.pdf' else ('web' if ext in ('.html', '.htm') else 'unknown')
    tr.log('N0.doc_type', dt, 'by extension', ext=ext)
    return dt


# ---------- N1 ----------
def classify_pdf(path, tr):
    doc = pymupdf.open(str(path))
    n_pages = doc.page_count
    chars = sum(len(p.get_text()) for p in doc)
    embedded = sum(len(p.get_images(full=True)) for p in doc)
    # vector-drawing signal: pages with many vector paths but no embedded raster -> vector structures
    vec_pages = 0
    for p in doc:
        try:
            if len(p.get_drawings()) > 40 and len(p.get_images()) == 0:
                vec_pages += 1
        except Exception:
            pass
    doc.close()
    cpp = chars / max(n_pages, 1)
    scanned = cpp < DIGITAL_MIN_CHARS_PER_PAGE
    vector_figures = vec_pages > 0 and embedded < n_pages
    tr.log('N1.pdf_kind', 'scanned' if scanned else 'digital',
           'chars/page %.0f vs gate %d' % (cpp, DIGITAL_MIN_CHARS_PER_PAGE),
           n_pages=n_pages, embedded_figs=embedded, vec_pages=vec_pages, vector_figures=vector_figures)
    return {'n_pages': n_pages, 'scanned': scanned, 'embedded_figs': embedded,
            'vector_figures': vector_figures}


# ---------- N2 ----------
def ingest_text(path, feat, tr, *, math_tables=False, force_engine=None):
    route = force_engine or ('mistral' if feat['scanned'] else ('mathpix' if math_tables else 'pymupdf'))
    try:
        from ocr.dispatch import extract as ocr_extract
        res = ocr_extract(path, math_tables=math_tables, force_engine=force_engine)
        eng, text = res['engine'], res['text'] or ''
        conf = getattr(res.get('confidence'), 'min_confidence', None)
        tr.log('N2.ingest', eng, 'routed=%s scanned=%s math_tables=%s' % (route, feat['scanned'], math_tables),
               chars=len(text), min_conf=conf, review_tokens=len(res.get('review') or []))
        return {'engine': eng, 'text': text, 'min_conf': conf, 'figures': res.get('figures') or []}
    except Exception as e:
        # decision layer must not die on a missing OCR backend; fall back to local text
        from ocr.pdf_extract import extract_text
        text = extract_text(path)
        tr.log('N2.ingest', 'pymupdf(fallback)', 'dispatch error: %s' % repr(e)[:60], chars=len(text))
        return {'engine': 'pymupdf', 'text': text, 'min_conf': None, 'figures': []}


# ---------- N3 ----------
def prepare_figures(path, feat, tr, out_dir):
    """vector->raster. For OCSR we render whole pages (universal: covers vector drawings that
    embedded-image extraction misses, exactly how ocsr_extract feeds OpenChemIE moldet)."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(path)); m = pymupdf.Matrix(RASTER_DPI / 72, RASTER_DPI / 72)
    pages = []
    for pno in range(doc.page_count):
        fp = f'{out_dir}/pg{pno:02d}.png'
        doc[pno].get_pixmap(matrix=m).save(fp); pages.append(fp)
    doc.close()
    why = ('vector figures present -> rasterized' if feat['vector_figures']
           else 'rasterized pages as universal OCSR input')
    tr.log('N3.figures', 'raster:%d pages@%ddpi' % (len(pages), RASTER_DPI), why,
           embedded_available=feat['embedded_figs'])
    return pages


# ---------- N4 ----------
def strategy_node(text, feat, tr, *, name_col_values=None):
    strat = classify_strategy(text, name_col_values)
    coupling = None
    # OCR<->strategy coupling: OPSIN needs pristine names; if text came from a weak source on a
    # scanned/low-text doc, flag to re-ingest via Mathpix before trusting names.
    if strat == 'opsin' and feat['scanned']:
        coupling = 'reingest_mathpix'
    tr.log('N4.strategy', strat,
           'IUPAC-name density / drug-name heuristic' + (' ; COUPLING:%s' % coupling if coupling else ''),
           coupling=coupling)
    return strat, coupling


# ---------- N5 ----------
def _ocsr_pool(paper, page_images, core_smarts, results_dir, tr):
    """Ensemble pool. PRIMARY = claude-opus vision on rendered pages (dominant: antibiotics 26/57,
    intechopen 2/4). BASE = free local MolScribe+DECIMER (cached / 3080). Gemini DROPPED (0 marginal
    gold + dilutes precision: antibiotics F1 0.161 -> 0.120 with it)."""
    from chemx.smiles_router import smiles_claude_vision
    cpath = '%s/claudepg_%s.json' % (results_dir, paper)
    if os.path.exists(cpath):
        tr.log('N5.ocsr.claude', 'cached', 'reuse claude-vision pool')
    elif page_images:
        cl = smiles_claude_vision(page_images, core_smarts=core_smarts)
        json.dump([{'canon': x} for x in cl], open(cpath, 'w'))
        tr.log('N5.ocsr.claude', '%d structs (live)' % len(cl), 'claude-opus vision (PRIMARY)')
    merged = ocsr_ensemble_pool(results_dir, paper, core_smarts)
    tr.log('N5.ocsr', 'ensemble pool:%d' % len(merged),
           'Claude(primary) + MolScribe + DECIMER free base; Gemini dropped', sources='claudepg+molscribe+decimer')
    return merged


def run_strategy(strat, text, paper, page_images, *, core_smarts, results_dir, name_map, tr):
    per_cid, enrichment = {}, []
    if strat == 'opsin':
        per_cid = smiles_opsin(text); enrichment = list(per_cid.values())
        tr.log('N5.opsin', '%d names->SMILES' % len(per_cid), 'claude-opus IUPAC pull + OPSIN')
    elif strat == 'pubchem' and name_map:
        per_cid = smiles_pubchem(name_map); enrichment = list(per_cid.values())
        tr.log('N5.pubchem', '%d names->SMILES' % len(per_cid), 'PubChem PUG REST')
    pool = _ocsr_pool(paper, page_images, core_smarts, results_dir, tr)
    cand = union_clean(enrichment, pool, core_smarts)
    return per_cid, cand


# ---------- N7 ----------
def gates(cand, per_cid, min_conf, tr):
    review = []
    if min_conf is not None and min_conf < 0.92:
        review.append('low_ocr_conf:%.2f' % min_conf)
    if not cand:
        review.append('no_smiles_candidates')
    tr.log('N7.gates', 'OK' if not review else 'REVIEW', 'confidence+completeness',
           candidates=len(cand), per_cid=len(per_cid), flags=';'.join(review) or 'none')
    return review


# ---------- driver ----------
def run(pdf_path, *, paper=None, core_smarts='c1ccc2ncnc2c1', results_dir=os.path.join(_ROOT, 'chemx', 'results'),
        name_map=None, name_col_values=None, math_tables=False, raster_dir=None):
    paper = paper or Path(pdf_path).stem
    tr = Trace()
    print('=== %s ===' % paper, flush=True)
    dt = detect_doc_type(pdf_path, tr)
    if dt != 'pdf':
        tr.log('END', 'unsupported', 'web path is a stub for now'); return {'trace': tr.dump()}
    feat = classify_pdf(pdf_path, tr)
    ing = ingest_text(pdf_path, feat, tr, math_tables=math_tables)
    strat, coupling = strategy_node(ing['text'], feat, tr, name_col_values=name_col_values)
    if coupling == 'reingest_mathpix':
        ing = ingest_text(pdf_path, feat, tr, math_tables=True, force_engine='mathpix')
    rdir = raster_dir or ('/tmp/pg_%s' % paper)
    pages = prepare_figures(pdf_path, feat, tr, rdir)  # always: Claude-vision OCSR is the strong general lever
    per_cid, cand = run_strategy(strat, ing['text'], paper, pages,
                                 core_smarts=core_smarts, results_dir=results_dir, name_map=name_map, tr=tr)
    review = gates(cand, per_cid, ing['min_conf'], tr)
    return {'paper': paper, 'doc_type': dt, 'scanned': feat['scanned'], 'engine': ing['engine'],
            'strategy': strat, 'per_cid': per_cid, 'candidates': cand, 'review': review,
            'trace': tr.dump()}


if __name__ == '__main__':
    out = run(sys.argv[1], paper=(sys.argv[2] if len(sys.argv) > 2 else None))
    print('\nRESULT: strategy=%s engine=%s candidates=%d review=%s'
          % (out.get('strategy'), out.get('engine'), len(out.get('candidates', [])), out.get('review')))
