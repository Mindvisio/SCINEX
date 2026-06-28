"""GROBID client: PDF -> document structure (section heads in reading order + cited DOIs).

Fills PaperNode.sections / PaperNode.references for the citation graph and L3 structural questions.
Needs a running GROBID service (docker run -p 8070:8070 grobid/grobid:0.8.2.1-crf); endpoint via
GROBID_URL (default http://localhost:8070). The CRF image suffices -- we use only fulltext/citation
segmentation, not the deep-learning models. All functions degrade to empty output if GROBID is down.
"""
from __future__ import annotations
import os
import re
import httpx
import xml.etree.ElementTree as ET

GROBID_URL = os.environ.get("GROBID_URL", "http://localhost:8070")
_TEI = "{http://www.tei-c.org/ns/1.0}"
_DOI = re.compile(r"10\.\d{4,9}/\S+")


def _q(tag: str) -> str:
    return _TEI + tag


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split())


def is_alive(url: str | None = None) -> bool:
    base = (url or GROBID_URL).rstrip("/")
    try:
        return httpx.get(base + "/api/isalive", timeout=5).text.strip() == "true"
    except Exception:
        return False


def process_pdf(pdf_path: str, *, url: str | None = None, timeout: float = 180.0):
    """POST a PDF to GROBID processFulltextDocument -> TEI-XML string, or None on failure."""
    base = (url or GROBID_URL).rstrip("/")
    try:
        with open(pdf_path, "rb") as fh:
            r = httpx.post(base + "/api/processFulltextDocument",
                           files={"input": (os.path.basename(pdf_path), fh, "application/pdf")},
                           data={"consolidateHeader": "0", "consolidateCitations": "0"},
                           timeout=timeout)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def parse_tei(tei: str) -> dict:
    """Extract {title, sections (body reading order), references (cited DOIs)} from GROBID TEI."""
    try:
        root = ET.fromstring(tei)
    except Exception:
        return {"title": "", "sections": [], "references": []}
    title = ""
    for ts in root.iter(_q("titleStmt")):
        t = ts.find(_q("title"))
        if t is not None:
            title = _text(t)
            break
    sections = []
    body = next(iter(root.iter(_q("body"))), None)
    if body is not None:
        for div in body.iter(_q("div")):
            head = div.find(_q("head"))
            if head is not None:
                h = _text(head)
                if h:
                    sections.append(h)
    refs = []
    for bibl in root.iter(_q("biblStruct")):
        for idno in bibl.iter(_q("idno")):
            if (idno.get("type") or "").upper() == "DOI":
                m = _DOI.search(_text(idno))
                if m:
                    refs.append(m.group(0).rstrip(".)"))
                    break
    refs = list(dict.fromkeys(refs))                        # dedup, keep order
    return {"title": title, "sections": sections, "references": refs}


def document_structure(pdf_path: str, *, url: str | None = None) -> dict:
    """PDF -> {title, sections, references}; empty fields if GROBID is down or parsing fails."""
    tei = process_pdf(pdf_path, url=url)
    return parse_tei(tei) if tei else {"title": "", "sections": [], "references": []}
