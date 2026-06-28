"""Deterministic detectors shared by text/table extractors: is-this-a-SMILES (RDKit-checked),
split a table header into (property, unit), and find inline SMILES/InChI tokens in free text.
"""
from __future__ import annotations
import re
from typing import Optional, Tuple

_STRUCT_CHARS = set("()=#[]/\\@+-.123456789")
_UNIT_TOKENS = ("nm", "um", "µm", "μm", "mm", "pm", "fm", "m", "g/l", "mg/ml", "ug/ml", "µg/ml",
                "mg/l", "ng/ml", "g/mol", "da", "kda", "°c", "c", "k", "%", "mol/l", "mmol/l", "umol/l")
_INCHI = re.compile(r"InChI=1S?/[^\s,;]+")


def _rdkit():
    from rdkit import Chem
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")
    return Chem


def looks_like_smiles(s: Optional[str]) -> bool:
    """Conservative: RDKit-parseable AND structurally non-trivial (avoids treating short
    alphabetic names/codes as SMILES)."""
    if not s:
        return False
    t = s.strip()
    if not t or " " in t or len(t) < 3 or len(t) > 300:
        return False
    if not any(c in _STRUCT_CHARS for c in t) and len(t) < 6:
        return False
    try:
        return _rdkit().MolFromSmiles(t) is not None
    except Exception:
        return False


def split_prop_unit(header: str) -> Tuple[str, Optional[str]]:
    """'IC50 (nM)' -> ('IC50','nM'); 'IC50, µM' -> ('IC50','µM'); 'MW (g/mol)' -> ('MW','g/mol')."""
    if not header:
        return header, None
    h = header.strip()
    unit = None
    m = re.search(r"[\(\[\{]\s*([^()\[\]{}]+?)\s*[\)\]\}]\s*$", h)
    if m and m.group(1).lower().strip() in _UNIT_TOKENS:
        unit = m.group(1).strip()
        h = h[:m.start()].strip()
    else:
        m2 = re.search(r",\s*([A-Za-zµμ%/0-9]+)\s*$", h)
        if m2 and m2.group(1).lower().strip() in _UNIT_TOKENS:
            unit = m2.group(1).strip()
            h = h[:m2.start()].strip()
    return h.strip(" :–-"), unit


def find_inline_structures(text: str):
    """Yield ('smiles'|'inchi', token, context) for RDKit-valid SMILES / InChI strings in text."""
    if not text:
        return
    for m in _INCHI.finditer(text):
        tok = m.group(0).rstrip(".,;)")
        ctx = text[max(0, m.start() - 40):m.end() + 10].replace("\n", " ")
        yield "inchi", tok, ctx
    # SMILES: scan whitespace-delimited tokens; cheap pre-filter then RDKit-confirm
    for m in re.finditer(r"(?<![\w/])([A-Za-z0-9@+\-\[\]()=#%/\\.]{6,200})(?![\w])", text):
        tok = m.group(1).strip(".,;)")
        if "InChI" in tok or tok.isalpha() or tok.isdigit():
            continue
        if not any(c in _STRUCT_CHARS for c in tok):
            continue
        if looks_like_smiles(tok):
            ctx = text[max(0, m.start() - 40):m.end() + 10].replace("\n", " ")
            yield "smiles", tok, ctx