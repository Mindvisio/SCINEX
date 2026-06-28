"""OpenChemIE figure/text extraction for the chem-db pipeline (the 'fully OpenChemIE' path).

Replaces the DECIMER-Segmentation scheme layer. Calls the OpenChemIE worker (subprocess to
.venv-openchemie) once for all PDFs, then in the runtime venv:
  - molecules (every [Mol] bbox + coref label) -> resolve_coref (cap '*' -> specific) -> Records
    (source_type='figure'); numeric labels populate a {label: SMILES} map for the activity join.
  - ChemRxnExtractor prep/yield sentences -> Records (source_type='text', property='yield').

Why OpenChemIE: its trained molecule<->identifier coreference recovered 40 numeric label links
across 8 papers vs 3 from the geometric heuristic; scaffold_graft.resolve_coref then turns the
markush '*' output into specific structures, side-stepping OCSR of fused cores.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile

from hw_chemdb.record import Record
from hw_chemdb.scaffold_graft import resolve_coref

_DEF_OCE = "/root/scinex/.venv-openchemie/bin/python"
OCE_PY = os.environ.get("OPENCHEMIE_PYTHON") or (_DEF_OCE if os.path.exists(_DEF_OCE) else sys.executable)
_OCE_WORKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "ocr", "openchemie_worker.py")
_NUM = re.compile(r"\((\d{1,3}[a-z]?)\)")
_NUM_BARE = re.compile(r"\b(\d{1,3}[a-z]?)\b")


def run_openchemie(pdfs, *, do_reactions=False, dpi=200, batch_size=4, timeout=7200):
    """Run the OpenChemIE worker over all PDFs -> {pdf: {molecules, reactions_text}}."""
    cfg = {"pdfs": list(pdfs), "do_reactions": do_reactions, "dpi": dpi, "batch_size": batch_size}
    fd, cfg_path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    fd, out_path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    json.dump(cfg, open(cfg_path, "w"))
    try:
        subprocess.run([OCE_PY, _OCE_WORKER, cfg_path, out_path],
                       text=True, timeout=timeout, check=False)  # inherit stdout -> pipeline log
        return json.load(open(out_path))
    except Exception:
        try:
            return json.load(open(out_path))      # partial checkpoint, if any
        except Exception:
            return {}
    finally:
        for p in (cfg_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _heavy(smiles):
    """Heavy-atom count of the LARGEST fragment (rejects disconnected debris like 'C.C.C...')."""
    try:
        from rdkit import Chem
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return 0
        frags = Chem.GetMolFrags(m, asMols=True, sanitizeFrags=False)
        return max((f.GetNumHeavyAtoms() for f in frags), default=0)
    except Exception:
        return 0


def _label_token(label):
    """Compound number from a coref label. Prefer a parenthesised id ('Rimonabant (1)' -> 1,
    'SLV319 (2)' -> 2), else a bare token ('14c' -> 14c, '8' -> 8)."""
    if not label:
        return None
    m = _NUM.search(label) or _NUM_BARE.search(label)
    return m.group(1) if m else None


def build_records(pdf_path, result, *, min_heavy_atoms=12):
    """-> (records, label_map) for one PDF's OpenChemIE result."""
    name = os.path.basename(pdf_path)
    records, label_map = [], {}
    for mol in result.get("molecules", []):
        smi, status, note = resolve_coref(mol.get("smiles"))
        if not smi or status == "failed":
            continue
        if _heavy(smi) < min_heavy_atoms:                 # drop R-group fragments / debris
            continue
        label = (mol.get("label") or "").strip() or None
        tok = _label_token(label)
        rec = Record(
            source_pdf=name, source_page=mol.get("page"), source_type="figure",
            extractor="openchemie:coref" if label else "openchemie:moldet",
            evidence=("coref label=%s" % label) if label else "figure structure (no label)",
            smiles_raw=smi, name_raw=label,
        )
        if status == "review":
            rec.flag_review("OpenChemIE " + note)
        records.append(rec)
        if tok and tok not in label_map:
            label_map[tok] = smi
    for rx in result.get("reactions_text", []):
        yld = rx.get("yield")
        if not yld:
            continue
        prod = (rx.get("products") or [None])[0]
        rec = Record(
            source_pdf=name, source_page=rx.get("page"), source_type="text",
            extractor="openchemie:chemrxn",
            evidence=rx.get("sentence", "")[:240],
            name_raw=(prod or None), property="yield", value_raw=yld, unit_raw="%",
        )
        rec.flag_review("ChemRxnExtractor prep/yield event")
        records.append(rec)
    return records, label_map


_LABEL_TOKEN = re.compile(r"(\d{1,3}[a-z]?)")


def attach_structures(records, label_maps) -> int:
    """Fill structure-less table/text rows whose compound LABEL matches an OpenChemIE coref structure
    from the SAME pdf. Sets smiles_raw so the resolver canonicalises + enriches. Returns count."""
    filled = 0
    for rec in records:
        if rec.smiles_raw or rec.smiles_canonical or not rec.name_raw:
            continue
        lmap = label_maps.get(rec.source_pdf)
        if not lmap:
            continue
        m = _LABEL_TOKEN.match(rec.name_raw.strip())
        if m and m.group(1) in lmap:
            rec.smiles_raw = lmap[m.group(1)]
            rec.extractor = (rec.extractor + "+openchemie").strip("+")
            rec.flag_review("structure from OpenChemIE coref (label-matched, verify)")
            filled += 1
    return filled