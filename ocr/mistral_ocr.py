"""Mistral OCR 4 (mistral-ocr-latest = mistral-ocr-4-0): scanned/image PDF -> markdown text +
per-word confidence + image bboxes. API-based (MISTRAL_API_KEY), direct from RU (no geoblock).
Used by the OCR dispatcher as the scanned-PDF rung and the confidence source.
"""
from __future__ import annotations
import base64
import os
from pathlib import Path

ENDPOINT = "https://api.mistral.ai/v1/ocr"
MODEL = "mistral-ocr-latest"


def _key():
    k = os.environ.get("MISTRAL_API_KEY")
    if not k:
        raise RuntimeError("MISTRAL_API_KEY unset")
    return k


def ocr_pdf(pdf_path, *, timeout: int = 180, want_images: bool = False) -> dict:
    """PDF -> raw Mistral OCR response (pages[], usage_info). Per-page confidence under
    page['confidence_scores'] (per-word). want_images=True also returns base64 crops."""
    import httpx
    b64 = base64.b64encode(Path(pdf_path).read_bytes()).decode()
    body = {"model": MODEL,
            "document": {"type": "document_url",
                         "document_url": f"data:application/pdf;base64,{b64}"},
            "include_image_base64": bool(want_images),
            "confidence_scores_granularity": "word"}
    r = httpx.post(ENDPOINT, headers={"Authorization": f"Bearer {_key()}"}, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def extract_pdf_mistral(pdf_path, *, timeout: int = 180, fig_dir=None) -> dict:
    """PDF -> {text, n_pages, confidence (OCRConfidence over all pages), figures, tables, pages_raw}.
    confidence aggregates the per-word scores across pages. When fig_dir is set, Mistral image
    regions are decoded to disk as real figure crops (bbox-accurate) -- the scanned-PDF figure path.
    """
    from ocr.confidence import from_mistral_page, OCRConfidence
    want_images = fig_dir is not None
    d = ocr_pdf(pdf_path, timeout=timeout, want_images=want_images)
    pages = d.get("pages", [])
    text = "\n\n".join(p.get("markdown", "") for p in pages)
    toks, page_confs, mins = [], [], []
    for i, p in enumerate(pages):
        c = from_mistral_page(p, page_idx=i)
        if c.tokens:
            toks.extend(c.tokens)
            page_confs.append(c.page_confidence)
            mins.append(c.min_confidence)
    conf = OCRConfidence(
        engine="mistral",
        page_confidence=(sum(page_confs) / len(page_confs)) if page_confs else 0.0,
        min_confidence=min(mins) if mins else 0.0,
        tokens=toks)
    figures = _save_mistral_figures(pages, fig_dir) if want_images else []
    return {"text": text, "n_pages": len(pages), "confidence": conf,
            "figures": figures, "tables": [], "pages_raw": pages}


def _save_mistral_figures(pages, fig_dir) -> list:
    """Decode Mistral per-page image regions to PNG/JPG crops + bbox. Returns figure dicts
    {fig_id, image_path, caption, page, bbox} compatible with ocr.pdf_extract figures."""
    import base64 as _b64
    from pathlib import Path
    out = Path(fig_dir)
    out.mkdir(parents=True, exist_ok=True)
    figs = []
    for i, p in enumerate(pages):
        for j, im in enumerate(p.get("images", []) or []):
            uri = im.get("image_base64") or ""
            meta, _, data = uri.partition(",") if "," in uri else ("", "", uri)
            if not data:
                continue
            ext = "jpg" if ("jpeg" in meta or "jpg" in meta) else ("png" if "png" in meta else "img")
            fid = f"p{i+1}m{j+1}"
            fp = out / f"{fid}.{ext}"
            try:
                fp.write_bytes(_b64.b64decode(data))
            except Exception:
                continue
            ann = im.get("image_annotation")
            cap = ann.strip() if isinstance(ann, str) and ann.strip() else ""
            figs.append({"fig_id": fid, "image_path": str(fp), "caption": cap, "page": i + 1,
                         "bbox": (im.get("top_left_x"), im.get("top_left_y"),
                                  im.get("bottom_right_x"), im.get("bottom_right_y"))})
    return figs
