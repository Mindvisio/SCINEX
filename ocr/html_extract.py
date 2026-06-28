"""HTML article page -> {text, figures, tables}. trafilatura main-text + BeautifulSoup figures/tables.

Figures: <figure><img> with caption from <figcaption>/alt; images downloaded to fig_dir if URL+base_url
(real crops for the vision-LLM). Tables: <table> flattened to text. text: trafilatura (tables included).
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urljoin


def _download_image(url, fdir, fid, timeout=20):
    import httpx
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        ct = r.headers.get("content-type", "").lower()
        low = url.lower()
        if "image" not in ct and not low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return None
        ext = ".png"
        for e in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            if e in ct or low.endswith(e):
                ext = ".jpg" if e == ".jpeg" else e
                break
        p = Path(fdir) / f"{fid}{ext}"
        p.write_bytes(r.content)
        return str(p)
    except Exception:
        return None


def _table_text(tb):
    rows = []
    for tr in tb.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def extract_html(html, *, base_url="", fig_dir=None, download_images=True):
    import trafilatura
    from bs4 import BeautifulSoup
    text = trafilatura.extract(html, include_tables=True, include_comments=False,
                               include_links=False, favor_recall=True) or ""
    soup = BeautifulSoup(html, "lxml")
    fdir = Path(fig_dir) if fig_dir else None
    if fdir:
        fdir.mkdir(parents=True, exist_ok=True)
    figures, n = [], 0
    for fig in soup.find_all("figure"):
        img = fig.find("img")
        src = (img.get("src") or img.get("data-src") or "") if img else ""
        capel = fig.find("figcaption")
        cap = (capel.get_text(" ", strip=True) if capel else (img.get("alt", "") if img else "")).strip()
        if not (src or cap):
            continue
        n += 1
        fid = f"f{n}"
        rec = {"fig_id": fid, "caption": cap[:500]}
        if download_images and src and fdir and base_url:
            ip = _download_image(urljoin(base_url, src), fdir, fid)
            if ip:
                rec["image_path"] = ip
        figures.append(rec)
    tables = []
    for ti, tb in enumerate(soup.find_all("table"), 1):
        t = _table_text(tb)
        if t.strip():
            tables.append({"table_id": f"t{ti}", "text": t[:4000]})
    return {"text": text, "figures": figures, "tables": tables}
