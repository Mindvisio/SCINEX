"""Full-text RESOLVE ladder + PARSE dispatch. DOI (+ optional urls/pmcid/abstract) -> corpus dict,
tagged by fulltext quality. Separates RESOLVE (source->content) from PARSE (content->{text,figures,
tables}). NO Sci-Hub yet: paywalled DOIs fall through to landing-HTML or abstract.

    from retrieval.fulltext import fetch_fulltext
    rec = fetch_fulltext("10.1038/s41467-023-44625-w", work_dir="/tmp/ft")
    # {paper_id, fulltext_level, source_url, text, figures, tables}

Levels best-first: pdf_oa (unpaywall) > jats (Europe PMC) > pdf_meta (landing citation_pdf_url) >
pdf_url / html (provided/landing) > abstract (OpenAlex -> Crossref).
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urljoin
import httpx

from retrieval.unpaywall import resolve_oa_pdf

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def _get(url, timeout=40):
    return httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)


def _is_pdf(resp) -> bool:
    ct = resp.headers.get("content-type", "").lower()
    return "application/pdf" in ct or resp.content[:5] == b"%PDF-"


def _save(content, path) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(content)
    return str(path)


def _citation_pdf_url(html, base_url):
    from bs4 import BeautifulSoup
    m = BeautifulSoup(html, "lxml").find("meta", attrs={"name": "citation_pdf_url"})
    return urljoin(base_url, m["content"]) if (m and m.get("content")) else None


def _doi_to_pmcid(doi):
    try:
        r = _get(f'{EPMC}/search?query=DOI:%22{doi}%22%20AND%20HAS_FT:Y&format=json&pageSize=1', 30)
        for res in r.json().get("resultList", {}).get("result", []):
            if res.get("pmcid"):
                return res["pmcid"]
    except Exception:
        pass
    return None


def _try_pdf_from_html(text, base, stem, wd):
    cu = _citation_pdf_url(text, base)
    if cu:
        rp = _get(cu)
        if rp.status_code == 200 and _is_pdf(rp):
            return {"level": "pdf_meta", "content_type": "pdf",
                    "path": _save(rp.content, wd / f"{stem}.pdf"), "source_url": cu}
    return None


def resolve(doi, *, urls=None, pmcid=None, work_dir="/tmp/fulltext", email=None):
    """-> {level, content_type, path|xml|html, source_url} or None. Best source first; no Sci-Hub."""
    stem = (doi or "doc").replace("/", "_")
    wd = Path(work_dir)
    landing = None
    # 1. unpaywall OA PDF (or OA html -> citation_pdf_url)
    if doi:
        oa = resolve_oa_pdf(doi, email=email)
        if oa:
            try:
                r = _get(oa)
                if r.status_code == 200 and _is_pdf(r):
                    return {"level": "pdf_oa", "content_type": "pdf",
                            "path": _save(r.content, wd / f"{stem}.pdf"), "source_url": oa}
                if r.status_code == 200 and r.text:
                    hit = _try_pdf_from_html(r.text, str(r.url), stem, wd)
                    if hit:
                        return hit
                    landing = landing or (r.text, str(r.url))
            except Exception:
                pass
    # 2. Europe PMC JATS
    pmcid = pmcid or (_doi_to_pmcid(doi) if doi else None)
    if pmcid:
        try:
            r = _get(f"{EPMC}/{pmcid}/fullTextXML")
            if r.status_code == 200 and r.content:
                return {"level": "jats", "content_type": "jats", "xml": r.content,
                        "source_url": f"{EPMC}/{pmcid}/fullTextXML"}
        except Exception:
            pass
    # 3. DOI landing -> citation_pdf_url -> PDF; else keep landing HTML
    if doi:
        try:
            r = _get(f"https://doi.org/{doi}")
            if r.status_code == 200 and r.text:
                hit = _try_pdf_from_html(r.text, str(r.url), stem, wd)
                if hit:
                    return hit
                landing = landing or (r.text, str(r.url))
        except Exception:
            pass
    # 4. provided urls -> pdf or html
    for u in (urls or []):
        try:
            r = _get(u)
            if r.status_code != 200:
                continue
            if _is_pdf(r):
                return {"level": "pdf_url", "content_type": "pdf",
                        "path": _save(r.content, wd / f"{stem}.pdf"), "source_url": u}
            if r.text:
                hit = _try_pdf_from_html(r.text, str(r.url), stem, wd)
                if hit:
                    return hit
                landing = landing or (r.text, str(r.url))
        except Exception:
            continue
    # 5. (Sci-Hub skipped) -> landing HTML if any
    if landing:
        return {"level": "html", "content_type": "html", "html": landing[0], "source_url": landing[1]}
    return None


def parse(ft, *, fig_dir=None, paper_id=None):
    ct = ft["content_type"]
    if ct == "pdf":
        from ocr.pdf_extract import extract_pdf
        ext = extract_pdf(ft["path"], fig_dir=fig_dir)
    elif ct == "jats":
        from ocr.jats_extract import extract_jats
        ext = extract_jats(ft["xml"])
    elif ct == "html":
        from ocr.html_extract import extract_html
        ext = extract_html(ft["html"], base_url=ft.get("source_url", ""), fig_dir=fig_dir)
    elif ct == "abstract":
        ext = {"text": ft.get("text", ""), "figures": [], "tables": []}
    else:
        ext = {"text": "", "figures": [], "tables": []}
    return {"paper_id": paper_id, "fulltext_level": ft["level"], "source_url": ft.get("source_url"),
            "text": ext["text"], "figures": ext["figures"], "tables": ext["tables"]}


def abstract_from_openalex(doi):
    """OpenAlex abstract, reconstructed from the inverted index -> str | None. Broader than Crossref."""
    try:
        r = _get(f"https://api.openalex.org/works/doi:{doi}", 25)
        idx = (r.json() or {}).get("abstract_inverted_index")
        if not idx:
            return None
        pos = {}
        for word, locs in idx.items():
            for p in locs:
                pos[p] = word
        return " ".join(pos[i] for i in sorted(pos)).strip() or None
    except Exception:
        return None


def abstract_from_crossref(doi):
    """Crossref abstract (JATS tags stripped) -> str | None."""
    import re as _re
    try:
        r = _get(f"https://api.crossref.org/works/{doi}", 25)
        ab = (r.json().get("message") or {}).get("abstract")
        if ab:
            return _re.sub(r"<[^>]+>", " ", ab).strip()
    except Exception:
        pass
    return None


def fetch_fulltext(doi, *, urls=None, pmcid=None, abstract=None, work_dir="/tmp/fulltext",
                   fig_dir=None, email=None, min_text=200):
    """RESOLVE + PARSE; abstract floor (OpenAlex -> Crossref) if full text is missing/thin.
    Empty/near-empty full-text records are dropped (-> None). -> dict | None."""
    ft = resolve(doi, urls=urls, pmcid=pmcid, work_dir=work_dir, email=email)
    rec = None
    if ft is not None:
        fd = fig_dir or f"{work_dir}/_figures/{(doi or 'doc').replace('/', '_')}"
        rec = parse(ft, fig_dir=fd, paper_id=doi)
    have_text = rec is not None and len((rec.get("text") or "").strip()) >= min_text
    if not have_text:
        ab = abstract
        if not ab and doi:
            ab = abstract_from_openalex(doi) or abstract_from_crossref(doi)
        if ab:
            rec = {"paper_id": doi, "fulltext_level": "abstract", "source_url": None,
                   "text": ab.strip(), "figures": [], "tables": []}
        else:
            rec = None
    return rec
