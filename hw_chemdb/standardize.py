"""Standardisation layer (slides 7-8): units -> canonical via pint (raw kept), categorical
variables -> controlled vocabulary. Deterministic; the conversion rule is recorded per record.

Unit families and canonical units:
  affinity/activity (IC50/Ki/Kd/EC50/Km/MIC)  -> nM     (molar concentration)
  solubility / mass-concentration             -> g/L
  temperature                                 -> degC
  molecular weight                            -> g/mol
  yield / purity / ee                         -> %
Unknown families pass through (value parsed, unit kept, flagged for review).
"""
from __future__ import annotations
import re
from typing import Optional, Tuple

import pint
from rapidfuzz import process, fuzz

# ---- pint registry with molar concentration -----------------------------------
_ureg = pint.UnitRegistry()
_ureg.define("molar = mol / liter = M")          # enables nM/uM/mM/pM via SI prefixes

# property name -> (canonical label, family)
_PROP_FAMILY = {
    "ic50": ("IC50", "conc"), "ec50": ("EC50", "conc"), "ce50": ("EC50", "conc"),
    "ki": ("Ki", "conc"), "kd": ("Kd", "conc"), "km": ("Km", "conc"),
    "mic": ("MIC", "conc"), "gi50": ("GI50", "conc"), "ld50": ("LD50", "conc"),
    "solubility": ("solubility", "massconc"), "logp": ("logP", "dimensionless"),
    "logd": ("logD", "dimensionless"), "clogp": ("clogP", "dimensionless"),
    "mw": ("MW", "mw"), "molecularweight": ("MW", "mw"), "molweight": ("MW", "mw"),
    "yield": ("yield", "pct"), "purity": ("purity", "pct"), "ee": ("ee", "pct"),
    "meltingpoint": ("melting_point", "temp"), "mp": ("melting_point", "temp"),
    "boilingpoint": ("boiling_point", "temp"), "bp": ("boiling_point", "temp"),
    "temperature": ("temperature", "temp"),
}
_CANON_UNIT = {"conc": "nM", "massconc": "g/L", "temp": "degC", "mw": "g/mol", "pct": "%"}


def normalize_property(name: Optional[str]) -> Tuple[Optional[str], str]:
    """raw property label -> (canonical label, family). Subscripts/spacing/case folded."""
    if not name:
        return None, "unknown"
    k = (name.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
         .lower().replace(" ", "").replace("-", "").replace("_", "").replace(".", ""))
    if k in _PROP_FAMILY:
        return _PROP_FAMILY[k]
    for key, val in _PROP_FAMILY.items():           # substring (e.g. 'ic50value')
        if key in k:
            return val
    return name.strip(), "unknown"


_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


_RANGE_MAX_RATIO = 1000.0   # hi/lo above this = implausibly wide range -> distrust midpoint


def parse_value(value_raw: Optional[str]):
    """verbatim value cell -> (central|None, operator|None, is_range, lo|None, hi|None).
    Non-destructive: ranges/comparators flagged, never collapsed silently. lo/hi are the
    endpoints of a TRUSTED ascending range (None for point values, comparators, or a range
    rejected by the sanity guard)."""
    if value_raw is None:
        return None, None, False, None, None
    s = str(value_raw).strip().replace("–", "-").replace("—", "-").replace(",", "")
    op = None
    m = re.match(r"\s*(>=|<=|>|<|≥|≤|~)", s)
    if m:
        op = m.group(1)
    nums = _NUM.findall(s)
    if not nums:
        return None, op, False, None, None
    if "±" in s:                                  # 12 ± 3 -> central 12, no min/max
        return float(nums[0]), op, False, None, None
    rng = re.search(r"(\d*\.?\d+)\s*[-–]\s*(\d*\.?\d+)", s)
    if rng:
        try:
            a, b = float(rng.group(1)), float(rng.group(2))
            if b < a:                                  # descending -> malformed (e.g. '258-61')
                return None, op, True, None, None
            lo, hi = min(a, b), max(a, b)
            if lo > 0 and hi / lo > _RANGE_MAX_RATIO:  # implausibly wide -> likely truncation/error
                return None, op, True, None, None
            return (a + b) / 2.0, op, True, lo, hi
        except ValueError:
            return None, op, True, None, None
    try:
        return float(nums[0]), op, False, None, None
    except ValueError:
        return None, op, False, None, None


def _canon_temp_unit(u):
    """Spelling-robust temperature unit -> pint name (degC/degF/kelvin), or None.
    Folds degree sign / 'deg(ree)' / spacing / case so C, °C, '° C', oC, celsius all map
    to one scale; likewise F/°F/oF/fahrenheit and K/°K/kelvin. Everything is converted
    to degC downstream, so the scale never depends on how the unit was written."""
    t = (u or "").strip().lower()
    for j in ("°", "º", "degrees", "degree", "deg", ".", " "):
        t = t.replace(j, "")
    if t in ("c", "oc", "celsius", "centigrade"):
        return "degC"
    if t in ("f", "of", "fahrenheit"):
        return "degF"
    if t in ("k", "ok", "kelvin"):
        return "kelvin"
    return None


def _convert_scalar(value, unit_raw, family):
    """Convert ONE numeric value to the family canonical unit; mirrors the conversion core
    of standardize_units (no flags/notes). -> float | None. Used for range endpoints."""
    if value is None:
        return None
    canon = _CANON_UNIT.get(family)
    if family in ("dimensionless", "unknown") or canon is None:
        return value
    u = (unit_raw or "").strip().replace("µ", "u").replace("μ", "u")
    if family == "temp" and u:
        tu = _canon_temp_unit(unit_raw)
        if tu is None:
            return None
        u = tu
    else:
        u = {"degC": "degC", "C": "degC", "°C": "degC", "oC": "degC", "K": "kelvin",
             "%": "percent", "": canon if family == "pct" else ""}.get(u, u)
    if family == "pct":
        return value
    if not u:
        return value
    try:
        q = _ureg.Quantity(value, u).to(canon if family != "temp" else "degC")
        return float(q.magnitude)
    except Exception:
        return None


def standardize_units(value_raw, unit_raw, family):
    """-> (value_std, unit_std, conversion_note, ok, detail). Keeps raw untouched."""
    central, op, is_range, _lo, _hi = parse_value(value_raw)
    canon = _CANON_UNIT.get(family)
    if family in ("dimensionless", "unknown") or canon is None:
        return central, (unit_raw or None), ("no canonical unit for family" if central is not None else None), \
               central is not None, "passthrough"
    if central is None:
        return None, canon, None, False, ("suspicious range" if is_range else "unparseable value")
    u = (unit_raw or "").strip().replace("µ", "u").replace("μ", "u")
    u = {"degC": "degC", "C": "degC", "°C": "degC", "oC": "degC", "K": "kelvin",
         "%": "percent", "": canon if family == "pct" else ""}.get(u, u)
    if family == "temp" and u:
        tu = _canon_temp_unit(unit_raw)
        if tu is None:
            return None, canon, None, False, "invalid unit: %s" % (unit_raw or "∅")
        u = tu
    if family == "pct":
        return central, "%", "already canonical", True, "ok"
    if not u:
        return central, canon, "unit missing → assumed " + canon, central is not None, "unit assumed"
    try:
        q = _ureg.Quantity(central, u).to(canon if family != "temp" else "degC")
        val = float(q.magnitude)
        if u.replace(" ", "") == canon.replace(" ", ""):
            note = "already canonical"
        else:
            factor = float(_ureg.Quantity(1.0, u).to(canon).magnitude) if family != "temp" else None
            note = ("1 %s = %g %s" % (unit_raw, factor, canon)) if factor is not None \
                   else ("%s → degC" % unit_raw)
        flag = "range" if is_range else ("comparator %s" % op if op else "ok")
        return val, canon, note, True, flag
    except Exception as e:                               # noqa: BLE001 - pint raises many types
        return None, canon, None, False, "invalid unit: %s" % (unit_raw or "∅")


# ---- categorical controlled vocabularies (slide 8) ----------------------------
_ASSAY_RULES = [("inhibit", "inhibition"), ("ic50", "inhibition"), ("bind", "binding"),
                ("antagon", "antagonism"), ("agon", "agonism"),
                ("cytotox", "cytotoxicity"), ("viabilit", "cytotoxicity"), ("mtt", "cytotoxicity"),
                ("antibacter", "antimicrobial"), ("antimicrob", "antimicrobial"), ("mic", "antimicrobial"),
                ("antiviral", "antiviral"), ("enzym", "enzymatic")]
_ASSAY_VOCAB = sorted({v for _, v in _ASSAY_RULES})

_ORG_RULES = [("escherichia", "Escherichia coli"), ("e. coli", "Escherichia coli"), ("e.coli", "Escherichia coli"),
              ("homo sapiens", "Homo sapiens"), ("human", "Homo sapiens"),
              ("staphylococcus", "Staphylococcus aureus"), ("s. aureus", "Staphylococcus aureus"),
              ("pseudomonas", "Pseudomonas aeruginosa"),
              ("mus musculus", "Mus musculus"), ("mouse", "Mus musculus"), ("murine", "Mus musculus"),
              ("rattus", "Rattus norvegicus"), ("rat", "Rattus norvegicus"),
              ("saccharomyces", "Saccharomyces cerevisiae"), ("yeast", "Saccharomyces cerevisiae")]


def _std_cat(raw, rules, vocab=None, fuzz_cutoff=88):
    if not raw:
        return None
    s = raw.lower().strip()
    for sub, canon in rules:
        if sub in s:
            return canon
    if vocab:
        hit = process.extractOne(s, vocab, scorer=fuzz.WRatio, score_cutoff=fuzz_cutoff)
        if hit:
            return hit[0]
    return None


def std_assay_type(raw):
    return _std_cat(raw, _ASSAY_RULES, _ASSAY_VOCAB)


def std_organism(raw):
    return _std_cat(raw, _ORG_RULES)


_CONC_MIN_NM = 1e-4   # 0.1 pM  — below this an IC50/Ki is implausibly potent
_CONC_WEAK_NM = 1e6   # 1 mM  - weak / near-inactive above this (still <= hard max)
_CONC_MAX_NM = 1e9    # 1 M     — above this it is almost surely a unit/parse error

def concentration_plausibility(value_nm, family, prop):
    """Cheap magnitude sanity-envelope for affinity/activity (family 'conc', already in nM).
    Returns a review note for out-of-range OR weak (>1 mM) magnitudes, else None.
    NOT a biological claim: the value is never altered or dropped — only flagged for review."""
    if family != "conc" or isinstance(value_nm, bool) or not isinstance(value_nm, (int, float)):
        return None
    if value_nm != value_nm or value_nm in (float("inf"), float("-inf")):  # NaN / inf
        return None
    p = prop or "conc"
    if value_nm <= 0:
        return "implausible %s: %g nM (<= 0)" % (p, value_nm)
    if value_nm > _CONC_MAX_NM:
        return "implausible %s: %g nM (> 1 M, likely unit/parse error)" % (p, value_nm)
    if value_nm < _CONC_MIN_NM:
        return "implausible %s: %g nM (< 0.1 pM)" % (p, value_nm)
    if value_nm > _CONC_WEAK_NM:
        return "weak %s: %g nM (> 1 mM, likely inactive)" % (p, value_nm)
    return None


def apply(rec) -> None:
    """Standardise a Record in place: property label+family -> unit conversion + categoricals."""
    canon_prop, family = normalize_property(rec.property)
    if canon_prop:
        rec.property = canon_prop
    if rec.value_raw is not None or rec.unit_raw is not None:
        v, u, note, ok, detail = standardize_units(rec.value_raw, rec.unit_raw, family)
        rec.value_std, rec.unit_std, rec.conversion_note = (round(v, 6) if isinstance(v, float) else v), u, note
        if not ok:
            rec.flag_review("unit standardisation: %s" % detail)
        elif detail in ("range", "unit assumed") or (detail or "").startswith("comparator"):
            rec.flag_review("value note: %s" % detail)
        pnote = concentration_plausibility(v, family, rec.property)
        if pnote:
            rec.flag_review(pnote)
        if family == "unknown" and rec.value_std is not None:
            rec.flag_review("unstandardised: unrecognised property '%s'" % (rec.property or ""))
        # structured bounds + operator (downstream filtering without re-parsing value_raw)
        _c, _op, _isr, _rlo, _rhi = parse_value(rec.value_raw)
        rec.value_op = _op
        if _isr and _rlo is not None:
            mn, mx = _convert_scalar(_rlo, rec.unit_raw, family), _convert_scalar(_rhi, rec.unit_raw, family)
            rec.value_min = round(mn, 6) if isinstance(mn, float) else mn
            rec.value_max = round(mx, 6) if isinstance(mx, float) else mx
        elif _op in (">", ">="):
            rec.value_min, rec.value_max = rec.value_std, None
        elif _op in ("<", "<="):
            rec.value_min, rec.value_max = None, rec.value_std
    rec.assay_type_std = std_assay_type(rec.assay_type_raw)
    rec.organism_std = std_organism(rec.organism_raw)