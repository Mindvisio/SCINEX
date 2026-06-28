"""OCR dispatcher -- selector-graph T/F branch. Route a PDF to the right TEXT engine while always
keeping PyMuPDF figure crops (the vision edge), and gate on confidence:

  PyMuPDF (digital: free, offline, figure crops)
     -> Mathpix         when math/tables critical
     -> Mistral OCR 4   when scanned (no text layer) -- per-word confidence
          -> Mathpix    escalation when Mistral min per-word conf < gate

Returns a unified contract + OCRConfidence (Mistral per-word AND Mathpix per-line via lines.json)
+ review flags.
"""
from __future__ import annotations

from ocr import pdf_extract

DIGITAL_MIN_CHARS_PER_PAGE = 100      # below -> no usable text layer -> scanned
MISTRAL_WORD_GATE = 0.92              # Mistral min per-word conf below this -> escalate + flag


def extract(pdf_path, *, fig_dir=None, math_tables: bool = False,
            want_confidence: bool = True, force_engine: str | None = None) -> dict:
    """Route a PDF. Returns {engine, text, figures, tables, n_pages, scanned, confidence, review}.
    figures always from PyMuPDF (real crops). math_tables=True prefers Mathpix text (LaTeX+tables).
    force_engine in {pymupdf, mathpix, mistral} overrides routing.
    """
    pdf_path = str(pdf_path)
    pm = pdf_extract.extract_pdf(pdf_path, fig_dir=fig_dir)
    figures, tables = pm["figures"], pm["tables"]
    n_pages = pm["n_pages"] or 1
    pm_text = pm["text"] or ""
    scanned = (len(pm_text) / max(n_pages, 1)) < DIGITAL_MIN_CHARS_PER_PAGE

    route = force_engine or ("mistral" if scanned else ("mathpix" if math_tables else "pymupdf"))
    engine, text, confidence, review = "pymupdf", pm_text, None, []

    if route == "mathpix":
        from ocr.mathpix import pdf_to_markdown, pdf_to_lines
        from ocr.confidence import from_mathpix_lines, low_conf
        try:
            text, engine = pdf_to_markdown(pdf_path), "pymupdf+mathpix"
            if want_confidence:
                confidence = from_mathpix_lines(pdf_to_lines(pdf_path))
                review = low_conf(confidence, MISTRAL_WORD_GATE)
        except Exception:
            engine, text = "pymupdf", pm_text          # fall back

    elif route == "mistral":
        from ocr.mistral_ocr import extract_pdf_mistral
        from ocr.confidence import low_conf
        from pathlib import Path
        mfig = fig_dir or str(Path(pdf_path).parent / "_figures" / Path(pdf_path).stem)
        try:
            mo = extract_pdf_mistral(pdf_path, fig_dir=mfig)
            text, engine = mo["text"], "mistral"
            if mo["figures"]:
                figures = mo["figures"]          # real Mistral crops > PyMuPDF whole-page images
            confidence = mo["confidence"] if want_confidence else None
            if confidence and confidence.min_confidence < MISTRAL_WORD_GATE:
                from ocr.mathpix import pdf_to_markdown, pdf_to_lines
                from ocr.confidence import from_mathpix_lines
                try:
                    text, engine = pdf_to_markdown(pdf_path), "mistral->mathpix"
                    if want_confidence:
                        confidence = from_mathpix_lines(pdf_to_lines(pdf_path))
                except Exception:
                    pass
            if confidence:
                review = low_conf(confidence, MISTRAL_WORD_GATE)
        except Exception:
            engine, text = "pymupdf", pm_text          # fall back

    return {"engine": engine, "text": text, "figures": figures, "tables": tables,
            "n_pages": n_pages, "scanned": scanned, "confidence": confidence, "review": review}
