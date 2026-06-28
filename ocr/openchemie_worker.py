"""OpenChemIE worker. Runs INSIDE .venv-openchemie (torch + TF + OpenChemIE). Reads a JSON job,
for each PDF renders pages itself (PyMuPDF -- bypasses the broken layoutparser PDF figure parser)
and runs:
  - extract_molecule_corefs_from_figures  -> every [Mol] bbox (SMILES) + molecule<->identifier links
  - extract_reactions_from_text_in_pdf    -> ChemRxnExtractor prep/yield events  (if do_reactions)
Emits JSON the runtime venv consumes, so torch/TF never enter it.

Usage: python openchemie_worker.py <in.json> <out.json>
  in.json  = {"pdfs": ["/path/a.pdf", ...], "do_reactions": false, "dpi": 200, "batch_size": 4}
  out.json = {"/path/a.pdf": {"molecules": [{page, smiles, label}],
                              "reactions_text": [{page, sentence, products, yield}]}, ...}
"""
import json
import os
import re
import sys

_YIELD = re.compile(r"(\d{1,3})\s*%", re.I)


def _txt(b):
    v = b.get("text")
    if isinstance(v, list):
        return " ".join(str(x) for x in v).strip()
    return (v or "").strip()


def _render(pdf, dpi):
    import fitz
    from PIL import Image
    d = fitz.open(pdf)
    pages = []
    for pg in d:
        px = pg.get_pixmap(dpi=dpi)
        pages.append(Image.frombytes("RGB", [px.width, px.height], px.samples))
    d.close()
    return pages


def _coref(model, pdf, dpi, batch_size):
    """-> list[{page, smiles, label}] : every [Mol] bbox, label set when coref-linked."""
    try:
        pages = _render(pdf, dpi)
    except Exception as e:
        sys.stderr.write("render %s: %s\n" % (pdf, e))
        return []
    try:
        res = model.extract_molecule_corefs_from_figures(pages, batch_size=batch_size)
    except Exception as e:
        sys.stderr.write("coref %s: %s\n" % (pdf, e))
        return []
    mols = []
    for pidx, fig in enumerate(res):
        if not isinstance(fig, dict):
            continue
        bboxes = fig.get("bboxes", [])
        label_for = {}
        for pair in fig.get("corefs", []):
            try:
                i, j = pair[0], pair[1]
                bi, bj = bboxes[i], bboxes[j]
                mol_idx = i if "smiles" in bi else (j if "smiles" in bj else None)
                idt = bj if mol_idx == i else bi
                if mol_idx is not None:
                    label_for[mol_idx] = _txt(idt)
            except Exception:
                pass
        for idx, b in enumerate(bboxes):
            if b.get("category") == "[Mol]" and b.get("smiles"):
                mols.append({"page": pidx + 1, "smiles": b["smiles"],
                             "label": label_for.get(idx) or None})
    return mols


def _reactions_text(model, pdf):
    """-> list[{page, sentence, products, yield}] from ChemRxnExtractor."""
    try:
        rxt = model.extract_reactions_from_text_in_pdf(pdf)
    except Exception as e:
        sys.stderr.write("chemrxn %s: %s\n" % (pdf, e))
        return []
    out = []
    for page in rxt:
        if not isinstance(page, dict):
            continue
        pno = page.get("page")
        for sent in page.get("reactions", []):
            toks = sent.get("tokens", [])
            text = " ".join(toks)
            ym = _YIELD.search(text)
            yld = ym.group(1) + "%" if ym else None
            products = []
            for rx in sent.get("reactions", []):
                if not isinstance(rx, dict):
                    continue
                for role, val in rx.items():
                    if "prod" not in str(role).lower():
                        continue
                    spans = val if isinstance(val, list) else [val]
                    for sp in spans:
                        try:
                            if isinstance(sp, (list, tuple)) and sp and isinstance(sp[0], (list, tuple)):
                                products.append(" ".join(str(t) for t in sp[0]))
                            elif isinstance(sp, (list, tuple)) and len(sp) >= 3:
                                products.append(" ".join(toks[sp[1]:sp[2] + 1]))
                        except Exception:
                            pass
            if yld or products:
                out.append({"page": pno, "sentence": text[:300],
                            "products": products[:4], "yield": yld})
    return out


def main():
    cfg = json.load(open(sys.argv[1]))
    out_path = sys.argv[2]
    dpi = cfg.get("dpi", 200)
    bs = cfg.get("batch_size", 4)
    do_rx = cfg.get("do_reactions", False)
    result = {}
    try:
        from openchemie import OpenChemIE
        model = OpenChemIE()
    except Exception as e:
        sys.stderr.write("OpenChemIE init failed: %s\n" % e)
        json.dump(result, open(out_path, "w"))
        return
    pdfs = cfg.get("pdfs", [])
    for idx, pdf in enumerate(pdfs, 1):
        entry = {"molecules": _coref(model, pdf, dpi, bs), "reactions_text": []}
        if do_rx:
            entry["reactions_text"] = _reactions_text(model, pdf)
        result[pdf] = entry
        json.dump(result, open(out_path, "w"))      # checkpoint after each pdf
        sys.stdout.write("[oce %d/%d] %s : %d molecules, %d rxn-sentences\n" % (
            idx, len(pdfs), os.path.basename(pdf), len(entry["molecules"]),
            len(entry["reactions_text"])))
        sys.stdout.flush()
    json.dump(result, open(out_path, "w"))


if __name__ == "__main__":
    main()