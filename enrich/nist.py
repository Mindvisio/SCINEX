"""NIST Chemistry WebBook lookup -> canonical chemical fields
(name, formula, mw, inchi, inchikey, cas_number, source_url). An OPEN-data enrichment source
alongside PubChem/ChEMBL. Fields live in the compound page's <li> elements + <span class=inchi-text>.
Direct from RU (US .gov, no geoblock). Maps 1:1 onto a store EntityNode (identifiers + formats).
"""
from __future__ import annotations
import re
import httpx
from bs4 import BeautifulSoup

BASE = "https://webbook.nist.gov"
SEARCH = BASE + "/cgi/cbook.cgi"
_UA = {"User-Agent": "Mozilla/5.0 (scinex enrichment)"}
_IKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


def _fetch(url, params=None):
    r = httpx.get(url, params=params, headers=_UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r


def _li_value(soup, label):
    """Value text of the <li> whose label starts with `label` (text after the first ':')."""
    for li in soup.find_all("li"):
        txt = re.sub(r"\s+", " ", li.get_text().strip())   # default get_text -> subscripts concat
        if txt.lower().startswith(label.lower()) and ":" in txt:
            return txt.split(":", 1)[1].strip()
    return None


def nist_lookup(name: str) -> dict | None:
    """Resolve a compound by name on NIST WebBook -> a cleaned dataset row, or None if not found."""
    r = _fetch(SEARCH, {"Name": name, "Units": "SI"})
    soup = BeautifulSoup(r.text, "html.parser")
    spans = soup.find_all("span", class_="inchi-text")
    if not spans:                                          # search-list page -> first compound link
        link = soup.select_one('a[href*="cbook.cgi?ID=C"]')
        if not link:
            return None
        r = _fetch(BASE + link.get("href"))
        soup = BeautifulSoup(r.text, "html.parser")
        spans = soup.find_all("span", class_="inchi-text")
    inchi = inchikey = None
    for sp in spans:
        t = sp.get_text(strip=True)
        if t.startswith("InChI="):
            inchi = t
        elif _IKEY.match(t):
            inchikey = t
    title = soup.title.get_text(strip=True) if soup.title else name
    mw = _li_value(soup, "Molecular weight")
    return {
        "name": title,
        "formula": _li_value(soup, "Formula"),
        "mw": float(mw) if mw and re.match(r"^[0-9.]+$", mw) else None,
        "inchi": inchi,
        "inchikey": inchikey,
        "cas_number": _li_value(soup, "CAS Registry Number"),
        "source_url": str(r.url),
    }
