"""Figure extraction: structure-image crops -> compound Records via OCSR.

Reuses scinex's RDKit-arbitrated OCSR (ocr.ocsr.images_to_smiles) but with NO-LLM engines only:
MolScribe (primary) + DECIMER (cross-check). Both SMILES are canonicalised by RDKit and reconciled
by InChIKey; agreement -> status 'ok', single-engine/disagreement -> review. Captions are
keyword-gated to structural figures by default (gate=False runs OCSR on every embedded image).
"""
from __future__ import annotations

from hw_chemdb.record import Record

_STRUCT_KW = ("structure", "compound", "scheme", "synthesi", "molecul", "derivativ",
              "skeletal", "analog", "inhibitor", "scaffold", "reaction")


def _structural(caption: str) -> bool:
    c = (caption or "").lower()
    return any(k in c for k in _STRUCT_KW)


def extract_figures(figures, pdf_name: str, *, use_molscribe: bool = True,
                    use_decimer: bool = True, gate: bool = True):
    engines = tuple(e for e, on in (("molscribe", use_molscribe), ("decimer", use_decimer)) if on)
    if not engines:
        return []
    sel = [f for f in (figures or [])
           if f.get("image_path") and (not gate or _structural(f.get("caption", "")))]
    if not sel:
        return []
    from ocr.ocsr import images_to_smiles                # imported lazily (loads RDKit/subprocess)
    mols = images_to_smiles([f["image_path"] for f in sel], engines=engines)
    out = []
    for f in sel:
        mol = mols.get(f["image_path"])
        if not mol or mol.status == "failed" or not mol.smiles:
            continue
        rec = Record(
            source_pdf=pdf_name, source_page=f.get("page"), source_type="figure",
            extractor="ocsr:" + (mol.backend or "+".join(engines)),
            evidence=(f.get("caption") or "structure figure")[:200],
            smiles_raw=mol.smiles, inchikey=mol.inchikey,
        )
        if mol.status != "ok":                            # single-engine or disagreement -> human check
            rec.flag_review("OCSR status=%s (backend=%s)" % (mol.status, mol.backend))
        if mol.alternatives:
            rec.evidence = (rec.evidence + " | alt: " + "; ".join(mol.alternatives[:2]))[:200]
        out.append(rec)
    return out