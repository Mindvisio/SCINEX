"""Scheme/figure structure extraction (the 'image -> structure' layer of the lecture).

Per PDF: rasterise pages -> DECIMER-Segmentation detects each molecule depiction (subprocess to its
TF venv) -> OCSR each crop (MolScribe + DECIMER, RDKit-arbitrated) -> read the printed label under
the structure with Tesseract (no LLM). Emits one Record per recognised structure (source_type=
'scheme') AND a {numeric_label: SMILES} map the pipeline uses to best-effort fill table/text rows
that carry only a compound number.

Reality check (empirical, these med-chem PDFs): labels are baked into the figure graphics and are
often NAMES (naltrexone, cyprodime) or absent/markush, and strip-OCR is noisy on fused cores, so
the number->structure join fires only sometimes. The structures themselves still enrich the dataset
and known compounds resolve via InChIKey -> PubChem.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile

from hw_chemdb.record import Record

_DEF_SEG = "/root/scinex/.venv-decimerseg/bin/python"
SEG_PY = os.environ.get("DECIMER_SEG_PYTHON") or (_DEF_SEG if os.path.exists(_DEF_SEG) else sys.executable)
_SEG_WORKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "ocr", "decimer_seg_worker.py")

_NUM_LABEL = re.compile(r"^\(?(\d{1,3}[a-z]?)\)?$")
_OCR_CFG = "--psm 7"


def _heavy_atoms(smiles):
    try:
        from rdkit import Chem
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
        m = Chem.MolFromSmiles(smiles)
        return m.GetNumHeavyAtoms() if m is not None else 0
    except Exception:
        return 0


def _rasterize(pdf_path, out_dir, dpi=200):
    """-> list[(page_no, png_path)] (1-indexed page_no)."""
    import pymupdf
    os.makedirs(out_dir, exist_ok=True)
    pages = []
    doc = pymupdf.open(pdf_path)
    stem = os.path.splitext(os.path.basename(pdf_path))[0][:40]
    for pno in range(doc.page_count):
        png = os.path.join(out_dir, "%s_p%d.png" % (stem, pno + 1))
        try:
            doc[pno].get_pixmap(dpi=dpi).save(png)
            pages.append((pno + 1, png))
        except Exception:
            continue
    doc.close()
    return stem, pages


def _segment(pages, crop_dir):
    """Run the DECIMER-Seg worker over page PNGs -> {tag: [{bbox,crop}]}."""
    cfg = {"pages": [{"png": png, "tag": "p%d" % pno} for pno, png in pages], "crop_dir": crop_dir}
    fd, cfg_path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    fd, out_path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    json.dump(cfg, open(cfg_path, "w"))
    try:
        subprocess.run([SEG_PY, _SEG_WORKER, cfg_path, out_path], capture_output=True, text=True,
                       timeout=1800, check=False)
        return json.load(open(out_path))
    except Exception:
        return {}
    finally:
        for p in (cfg_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _ocr_label(png_path, bbox, _cache={}):
    """Read the label printed just below a structure. bbox=(y0,x0,y1,x1) px.
    -> (raw_text, kind, value) with kind in {'number','name',None}."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return "", None, None
    img = _cache.get(png_path)
    if img is None:
        img = Image.open(png_path)
        _cache[png_path] = img
    W, H = img.size
    y0, x0, y1, x1 = bbox
    cx, w = (x0 + x1) // 2, (x1 - x0)
    half = max(70, w // 2)
    strip = img.crop((max(0, cx - half), max(0, y1 - 8), min(W, cx + half), min(H, y1 + 58)))
    try:
        raw = pytesseract.image_to_string(strip, config=_OCR_CFG).strip()
    except Exception:
        return "", None, None
    flat = " ".join(raw.split())
    token = flat.replace(" ", "")
    m = _NUM_LABEL.match(token)
    if m:
        return flat, "number", m.group(1)
    name = re.sub(r"[^A-Za-z0-9\-\(\), ]", "", flat).strip(" -,")
    letters = re.sub(r"[^A-Za-z]", "", name)
    if len(letters) >= 5 and len(name) <= 40:            # looks like a (trivial) chemical name
        return flat, "name", name
    return flat, None, None


def build_schemes(pdf_path, *, use_molscribe=True, use_decimer=True, dpi=200, work_root=None,
                  min_heavy_atoms=12):
    """-> (records, label_map). records: one per recognised scheme structure. label_map:
    {numeric_label: canonical_smiles} for best-effort number->structure join in the pipeline."""
    work_root = work_root or os.path.join(tempfile.gettempdir(), "hw_schemes")
    name = os.path.basename(pdf_path)
    page_dir = os.path.join(work_root, "pages")
    crop_dir = os.path.join(work_root, "crops")
    stem, pages = _rasterize(pdf_path, page_dir, dpi=dpi)
    if not pages:
        return [], {}
    seg = _segment(pages, crop_dir)
    png_by_tag = {"p%d" % pno: png for pno, png in pages}
    # collect all crops -> OCSR once (amortise model loads)
    crop_meta = []                                       # (tag, page_no, bbox, crop_path)
    for pno, png in pages:
        for item in seg.get("p%d" % pno, []):
            crop_meta.append(("p%d" % pno, pno, item["bbox"], item["crop"]))
    if not crop_meta:
        return [], {}
    engines = tuple(e for e, on in (("molscribe", use_molscribe), ("decimer", use_decimer)) if on)
    from ocr.ocsr import images_to_smiles
    mols = images_to_smiles([c[3] for c in crop_meta], engines=engines)
    records, label_map = [], {}
    for tag, pno, bbox, crop in crop_meta:
        mol = mols.get(crop)
        if not mol or mol.status == "failed" or not mol.smiles or not mol.inchikey:
            continue
        if _heavy_atoms(mol.smiles) < min_heavy_atoms:   # drop markush R-group fragments
            continue
        raw, kind, value = _ocr_label(png_by_tag[tag], bbox)
        rec = Record(
            source_pdf=name, source_page=pno, source_type="scheme",
            extractor="ocsr:" + (mol.backend or "+".join(engines)),
            evidence=("scheme structure p%d" % pno) + (" label=%s" % raw if raw else ""),
            smiles_raw=mol.smiles, inchikey=mol.inchikey,
            name_raw=value if kind == "name" else None,
        )
        if mol.status != "ok":
            rec.flag_review("OCSR scheme status=%s (backend=%s)" % (mol.status, mol.backend))
        records.append(rec)
        if kind == "number" and value not in label_map:
            label_map[value] = mol.smiles
    return records, label_map


_LABEL_TOKEN = re.compile(r"(\d{1,3}[a-z]?)")


def attach_scheme_structures(records, label_maps) -> int:
    """Best-effort: fill structure-less table/text rows whose compound LABEL matches a scheme
    structure from the SAME pdf. Returns count filled. Sets smiles_raw so the resolver canonicalises
    + PubChem-enriches downstream."""
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
            rec.extractor = (rec.extractor + "+scheme").strip("+")
            rec.flag_review("structure from scheme OCSR (label-matched, verify)")
            filled += 1
    return filled