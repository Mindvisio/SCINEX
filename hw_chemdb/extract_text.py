"""Text extraction (no LLM): regex property+unit patterns with nearest-compound association,
inline SMILES/InChI detection, and an OPSIN-scan NER pass over candidate name phrases. The regex
layer is the robust baseline; OPSIN turns systematic names into structure deterministically.

Compound<->property association in free text is heuristic and acknowledged-imperfect (slide 16):
measurements with no clearly attached compound are still recorded but flagged for review.
"""
from __future__ import annotations
import re

from hw_chemdb.record import Record
from hw_chemdb.detect import find_inline_structures

_SUBS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_CONC_UNIT = r"(?:[pnfuµμm]?M|nmol/L|µmol/L|umol/L|mmol/L|mol/L)"
_VAL = r"\d+\.?\d*(?:\s*[-–]\s*\d+\.?\d*)?"

_PATTERNS = [
    ("affinity", re.compile(
        r"\b(?P<prop>IC50|EC50|GI50|LD50|Ki|Kd|Km|MIC)\b\s*(?:value|of|was|is|=|:)*\s*"
        r"(?P<op>[<>≤≥~]?)\s*(?P<val>" + _VAL + r")\s*(?P<unit>" + _CONC_UNIT + r")", re.I)),
    ("solubility", re.compile(
        r"\bsolubilit\w*\b[^.\n]{0,25}?(?P<val>" + _VAL + r")\s*"
        r"(?P<unit>mg/mL|µg/mL|ug/mL|g/L|mg/L|ng/mL)", re.I)),
    ("melting_point", re.compile(
        r"\b(?:melting point|m\.?\s?p\.?)\b\s*(?:=|:|of)?\s*(?P<val>" + _VAL + r")\s*"
        r"(?P<unit>°?\s?C|K)\b")),
    ("logp", re.compile(r"\b(?P<prop>logP|logD|clogP)\b\s*(?:=|:|of)?\s*(?P<val>-?\d+\.?\d*)", re.I)),
    ("yield", re.compile(r"(?P<val>\d+\.?\d*)\s*%\s*yield|\byield\b[^.\n]{0,20}?(?P<val2>\d+\.?\d*)\s*%", re.I)),
]

_COMP_LABEL = re.compile(r"compound\s+(\d+[a-z]?)|\*\*([^*]{2,40})\*\*|\((\d+[a-z]?)\)", re.I)


def _nearest_compound(text: str, pos: int, window: int = 110):
    seg = text[max(0, pos - window):pos]
    last = None
    for m in _COMP_LABEL.finditer(seg):
        last = next(g for g in m.groups() if g)
    return last.strip() if last else None


def _regex_records(text: str, pdf_name: str):
    t = text.translate(_SUBS)
    out = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(t):
            gd = m.groupdict()
            prop = gd.get("prop") or kind
            val = gd.get("val") or gd.get("val2")
            if not val:
                continue
            unit = gd.get("unit")
            if kind == "yield":
                unit = "%"
            comp = _nearest_compound(t, m.start())
            ev = t[max(0, m.start() - 50):m.end() + 5].replace("\n", " ").strip()
            rec = Record(source_pdf=pdf_name, source_type="text", extractor="regex",
                         evidence=ev[:200], property=prop, value_raw=val, unit_raw=unit,
                         name_raw=comp)
            if not comp:
                rec.flag_review("measurement without attached compound")
            out.append(rec)
    return out


def _inline_structure_records(text: str, pdf_name: str):
    out = []
    for kind, tok, ctx in find_inline_structures(text):
        rec = Record(source_pdf=pdf_name, source_type="text", extractor="regex:struct",
                     evidence=ctx[:200])
        if kind == "smiles":
            rec.smiles_raw = tok
        else:                                            # InChI -> SMILES via RDKit (resolve canonicalises)
            try:
                from rdkit import Chem
                from rdkit import RDLogger
                RDLogger.DisableLog("rdApp.*")
                mol = Chem.MolFromInchi(tok)
                rec.smiles_raw = Chem.MolToSmiles(mol) if mol is not None else None
            except Exception:
                rec.smiles_raw = None
            if not rec.smiles_raw:
                continue
        out.append(rec)
    return out


# ---- OPSIN-scan NER: systematic chemical names in running text (deterministic, gives structure) ----
_LOCANT = re.compile(r"\d['′]?-|\d,\d")
_SUFFIX = re.compile(
    r"(?:ol|al|one|ane|ene|yne|oate|oic|amide|amine|aniline|phenol|benzene|benzoic|"
    r"pyridine|pyrimidine|furan|thiophene|imidazol\w*|indol\w*|azole|naphthalen\w*|"
    r"piperidin\w*|piperazin\w*|morpholin\w*|quinolin\w*|purine)$", re.I)
_TAIL = {"acid", "ester", "anhydride", "chloride", "bromide", "iodide", "oxide",
         "amine", "amide", "alcohol", "ketone"}
_STOP = {"alone", "clone", "zone", "ozone", "prone", "drone", "throne", "stone", "phone",
         "none", "done", "gone", "bone", "tone", "one", "shone", "scone",
         "machine", "routine", "engine", "define", "determine", "combine", "medicine",
         "marine", "examine", "imagine", "genuine", "cuisine", "famine", "outline",
         "baseline", "guideline", "decline", "airline", "online", "pipeline", "timeline",
         "headline", "deadline", "incline", "divine", "canine", "vaccine", "caffeine",
         "codeine", "protein", "table", "stable", "example", "sample", "variable",
         "available", "capable", "notable", "suitable", "valuable", "enable", "disable",
         "figure", "nature", "feature", "picture", "mixture", "structure", "temperature",
         "literature", "procedure", "measure", "pressure", "exposure", "future", "culture",
         "while", "title", "article", "profile", "mobile", "sterile", "volatile", "scheme"}


def _candidates(text):
    toks = [w.strip(".,;:()[]{}\"'‘’") for w in text.split()]
    out = set()
    for i, w in enumerate(toks):
        if len(w) < 4 or w.lower() in _STOP:
            continue
        if not (_LOCANT.search(w) or _SUFFIX.search(w)):
            continue
        out.add(w)
        if i + 1 < len(toks) and toks[i + 1].lower() in _TAIL:
            out.add(w + " " + toks[i + 1])
        if i > 0 and len(toks[i - 1]) >= 4 and toks[i - 1].lower() not in _STOP:
            out.add(toks[i - 1] + " " + w)
    return [c for c in out if 4 <= len(c) <= 60][:400]


def _opsin_records(text, pdf_name):
    """OPSIN over candidate name phrases (one batched JVM call). Valid systematic names become
    entity Records WITH structure; OPSIN itself rejects non-chemical phrases (returns empty)."""
    cands = _candidates(text)
    if not cands:
        return []
    try:
        import warnings
        from py2opsin import py2opsin
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            smis = py2opsin(cands)
    except Exception:
        return []
    if not isinstance(smis, list):
        return []
    out = []
    for name, smi in zip(cands, smis):
        smi = (smi or "").strip()
        if not smi:
            continue
        idx = text.find(name)
        ctx = text[max(0, idx - 30):idx + len(name) + 30].replace("\n", " ").strip() if idx >= 0 else name
        out.append(Record(source_pdf=pdf_name, source_type="text", extractor="opsin:text",
                          evidence=ctx[:200], name_raw=name, smiles_raw=smi))
    return out


def extract_text(text: str, pdf_name: str, use_opsin: bool = True):
    """No-LLM text extraction. Stack: regex properties + inline SMILES/InChI + OPSIN-scan NER
    (systematic names -> structure). All deterministic; no generative model."""
    if not text:
        return []
    recs = _regex_records(text, pdf_name) + _inline_structure_records(text, pdf_name)
    if use_opsin:
        recs += _opsin_records(text, pdf_name)
    return recs