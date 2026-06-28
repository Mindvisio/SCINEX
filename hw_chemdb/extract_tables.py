"""Table extraction: PyMuPDF markdown tables -> measurement Records.

Input = the `tables` list from ocr.pdf_extract.extract_tables (each {table_id, text=markdown, page}).
Heuristics: first column (or a name/compound/ligand/entry header) = the compound; columns whose
header names a known property (optionally with unit, e.g. 'IC50 (nM)') = measurements. One Record
per (row-compound, property-column) non-empty cell. Compound cells that are RDKit-valid SMILES go to
smiles_raw; otherwise name_raw.
"""
from __future__ import annotations
import re

from hw_chemdb.record import Record
from hw_chemdb.detect import looks_like_smiles, split_prop_unit
from hw_chemdb.standardize import normalize_property

_NAME_HDR = re.compile(r"name|compound|cmpd|ligand|entry|structure|code|molecule|drug|analyte|id\b",
                       re.I)


def _parse_markdown(md: str):
    rows = [ln for ln in md.splitlines() if ln.strip().startswith("|")]
    if len(rows) < 2:
        return None, []
    def cells(line):
        parts = line.strip().strip("|").split("|")
        return [c.strip() for c in parts]
    header = cells(rows[0])
    body = []
    for ln in rows[1:]:
        if re.match(r"^\s*\|?[\s:|\-]+\|?\s*$", ln):       # separator row of --- :--- etc.
            continue
        body.append(cells(ln))
    return header, body


def _compound_col(header):
    for i, h in enumerate(header):
        if _NAME_HDR.search(h or ""):
            return i
    return 0                                              # fallback: first column


def _property_cols(header, comp_idx):
    """-> list of (col_idx, canonical_property, unit_from_header)."""
    out = []
    for i, h in enumerate(header):
        if i == comp_idx or not h:
            continue
        prop_txt, unit = split_prop_unit(h)
        canon, family = normalize_property(prop_txt)
        if family != "unknown":                            # a recognised property column
            out.append((i, canon, unit))
    return out


def extract_tables(tables, pdf_name: str):
    records = []
    for tbl in tables or []:
        header, body = _parse_markdown(tbl.get("text", ""))
        if not header or not body:
            continue
        ci = _compound_col(header)
        prop_cols = _property_cols(header, ci)
        if not prop_cols:
            continue
        for row in body:
            if ci >= len(row):
                continue
            comp = (row[ci] or "").strip()
            if not comp or comp in {"-", "—", "n/a", "NA"}:
                continue
            is_smiles = looks_like_smiles(comp)
            for col, prop, unit in prop_cols:
                if col >= len(row):
                    continue
                cell = (row[col] or "").strip()
                if not cell or cell in {"-", "—", "n/d", "nd", "n/a", "NA", ""}:
                    continue
                rec = Record(
                    source_pdf=pdf_name, source_page=tbl.get("page"), source_type="table",
                    extractor="table",
                    evidence="[%s] %s = %s" % (tbl.get("table_id", "table"), header[col], cell),
                    property=prop, value_raw=cell, unit_raw=unit,
                )
                if is_smiles:
                    rec.smiles_raw = comp
                else:
                    rec.name_raw = comp
                records.append(rec)
    return records