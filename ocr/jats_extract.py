"""JATS full-text XML (Europe PMC fullTextXML) -> {text, figures, tables}. Most structured source.

text: section titles + paragraphs in document order. figures: <fig> label+caption (+ graphic href;
PMC image fetch = TODO). tables: <table-wrap> label+caption + flattened table text.
"""
from __future__ import annotations
from lxml import etree

_XLINK = "{http://www.w3.org/1999/xlink}href"


def _txt(el):
    return " ".join(" ".join(el.itertext()).split()) if el is not None else ""


def extract_jats(xml):
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    root = etree.fromstring(xml)
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    body = root.find(".//body")
    parts, seen = [], set()
    if body is not None:
        for el in body.iter():
            if el.tag == "title":
                t = _txt(el)
                if t:
                    parts.append("## " + t)
            elif el.tag == "p":
                par = el.getparent()
                if par is not None and par.tag in ("caption", "table-wrap", "fig"):
                    continue
                t = _txt(el)
                if t and id(el) not in seen:
                    seen.add(id(el)); parts.append(t)
    text = "\n\n".join(parts)
    figures = []
    for i, fig in enumerate(root.iter("fig"), 1):
        label = _txt(fig.find("label"))
        cap = _txt(fig.find("caption"))
        g = fig.find(".//graphic")
        href = (g.get(_XLINK) or g.get("href")) if g is not None else None
        figures.append({"fig_id": f"f{i}", "caption": (label + " " + cap).strip()[:600], "graphic": href})
    tables = []
    for i, tw in enumerate(root.iter("table-wrap"), 1):
        label = _txt(tw.find("label"))
        cap = _txt(tw.find("caption"))
        tbl = tw.find(".//table")
        tables.append({"table_id": f"t{i}",
                       "text": (label + " " + cap + "\n" + (_txt(tbl) if tbl is not None else "")).strip()[:4000]})
    return {"text": text, "figures": figures, "tables": tables}
