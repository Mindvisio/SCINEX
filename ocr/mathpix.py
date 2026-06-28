"""Thin OCR wrapper over the vendored Mathpix tool (ocr/mathpix_pdf.py).

One submit per PDF caches BOTH outputs by sha256 under data/cache/:
  <sha>.mathpix.md          -- Markdown (LaTeX math + tables)
  <sha>.mathpix.lines.json  -- per-line data (include_line_data): bbox(cnt/region), type,
                               confidence, confidence_rate. Feeds ocr/confidence.py gates.
Idempotent: re-uses cached outputs when the source sha matches.
"""
from __future__ import annotations
from pathlib import Path
import hashlib, json

from ocr.mathpix_pdf import _read_keys, submit_pdf, poll, download_format
from config import CACHE_DIR

_LINE_FIELDS = ("text", "type", "cnt", "region", "confidence", "confidence_rate")


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _run(pdf_path, *, force: bool = False):
    """Submit once; cache md + lines.json by sha. Returns (md_path, lines_path)."""
    pdf_path = Path(pdf_path)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stem = _sha256(pdf_path)[:16]
    md_path = CACHE_DIR / f"{stem}.mathpix.md"
    lines_path = CACHE_DIR / f"{stem}.mathpix.lines.json"
    if md_path.exists() and lines_path.exists() and not force:
        return md_path, lines_path
    app_id, app_key = _read_keys()
    pdf_id = submit_pdf(pdf_path, app_id, app_key)        # DEFAULT_OPTIONS now sets include_line_data
    poll(pdf_id, app_id, app_key)
    download_format(pdf_id, "md", md_path, app_id, app_key)
    try:
        download_format(pdf_id, "lines.json", lines_path, app_id, app_key)
    except Exception:
        lines_path.write_text("{}")                        # best-effort; md still usable
    return md_path, lines_path


def pdf_to_markdown(pdf_path, *, force: bool = False) -> str:
    md_path, _ = _run(pdf_path, force=force)
    return md_path.read_text(encoding="utf-8")


def pdf_to_lines(pdf_path, *, force: bool = False) -> list:
    """Per-line list: [{page, text, type, cnt, region, confidence, confidence_rate}]. [] if unavailable."""
    _, lines_path = _run(pdf_path, force=force)
    try:
        pages = json.loads(lines_path.read_text()).get("pages", [])
    except Exception:
        return []
    return [dict(page=pg.get("page"), **{k: ln.get(k) for k in _LINE_FIELDS})
            for pg in pages for ln in pg.get("lines", [])]
