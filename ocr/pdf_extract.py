"""Local PDF extraction for the QA corpus (PyMuPDF / pymupdf4llm). Free, offline, no per-page API cost.

extract_pdf(path) -> {text, figures, tables, n_pages}:
  - text   : clean markdown (pymupdf4llm; multi-column aware, tables inlined)
  - figures: REAL embedded image crops + nearest caption + image_path (handed to a vision-LLM at
             answer time -- strictly more than ITMO's text-only figure descriptions)
  - tables : PyMuPDF find_tables() -> markdown (also present inline in `text`)
Mathpix (ocr/mathpix.py) remains an optional higher-quality text/table backend.
"""
from __future__ import annotations
import re
from pathlib import Path
import pymupdf

_CAP = re.compile(r'^(fig(?:ure)?\.?\s*\d+)', re.I)


def extract_text(pdf_path: str) -> str:
    import pymupdf4llm
    return pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)


def _local_text(blocks, frect, max_gap: float = 160.0, cap_chars: int = 700) -> str:
    """Text blocks spatially adjacent to a figure (same column, small vertical gap), caption excluded
    -- the figure's local discussion. Lets us link surrounding-text entities without matching against
    the whole paper (which would link every entity to every figure)."""
    fx0, fy0, fx1, fy1 = frect.x0, frect.y0, frect.x1, frect.y1
    near = []
    for b in blocks:
        bt = (b[4] or "").strip()
        if not bt or _CAP.match(bt):
            continue
        bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
        h_ov = min(bx1, fx1) - max(bx0, fx0)            # horizontal overlap with the figure column
        v_gap = max(0.0, by0 - fy1, fy0 - by1)          # 0 if vertically overlapping the figure
        if h_ov > 0 and v_gap < max_gap:
            near.append((by0, " ".join(bt.split())))
    near.sort()
    return " ".join(t for _, t in near)[:cap_chars]


def extract_figures(pdf_path: str, fig_dir: str, min_w: int = 120, min_h: int = 120) -> list[dict]:
    """Embedded raster images above a size threshold -> PNG crops + nearest 'Figure N' caption."""
    doc = pymupdf.open(str(pdf_path))
    out = Path(fig_dir); out.mkdir(parents=True, exist_ok=True)
    figs, seen, n = [], set(), 0
    for pno, page in enumerate(doc):
        blocks = page.get_text("blocks")
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                pix = pymupdf.Pixmap(doc, xref)
            except Exception:
                continue
            if pix.width < min_w or pix.height < min_h:
                continue
            if pix.n >= 5:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            n += 1
            fid = f"p{pno+1}n{n}"
            fp = out / f"{fid}.png"
            try:
                pix.save(str(fp))
            except Exception:
                continue
            rects = page.get_image_rects(xref)
            frect = rects[0] if rects else None
            iy = frect.y1 if frect else 0.0
            cap, best = "", 1e9
            for b in blocks:
                bt = (b[4] or "").strip()
                if _CAP.match(bt):
                    d = abs(b[1] - iy)
                    if d < best:
                        best = d; cap = " ".join(bt.split())[:500]
            bbox = [frect.x0, frect.y0, frect.x1, frect.y1] if frect else None
            local = _local_text(blocks, frect) if frect else ""
            figs.append({"fig_id": fid, "image_path": str(fp), "caption": cap, "page": pno + 1,
                         "bbox": bbox, "text": local})
    doc.close()
    return figs


def extract_tables(pdf_path: str, max_tables: int = 40) -> list[dict]:
    doc = pymupdf.open(str(pdf_path))
    tabs = []
    for pno, page in enumerate(doc):
        try:
            found = page.find_tables()
        except Exception:
            continue
        for ti, t in enumerate(found.tables):
            try:
                md = (t.to_markdown() or "").strip()
            except Exception:
                md = ""
            if md:
                tabs.append({"table_id": f"p{pno+1}t{ti+1}", "text": md, "page": pno + 1})
            if len(tabs) >= max_tables:
                doc.close(); return tabs
    doc.close()
    return tabs


def extract_pdf(pdf_path: str, fig_dir: str | None = None) -> dict:
    p = Path(pdf_path)
    fdir = fig_dir or str(p.parent / "_figures" / p.stem)
    doc = pymupdf.open(str(p)); npages = doc.page_count; doc.close()
    return {"text": extract_text(pdf_path),
            "figures": extract_figures(pdf_path, fdir),
            "tables": extract_tables(pdf_path),
            "n_pages": npages}
