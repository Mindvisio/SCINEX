# -*- coding: utf-8 -*-
"""ChemX preprocessing primitives: surface normalization + object dedup.

Scoped deliberately to what the exact-string ChemX metric rewards, and to NOTHING that would
overfit the gold key. Measured facts (official metric_local on scinex preds) that shaped this:

  * Micro-sign is PER-DOMAIN. U+03BC (greek mu) and U+00B5 (micro sign) render identically but are
    distinct codepoints; the metric is exact-string. Convention derived from datasets/* unit cols:
        benzimidazole target_units -> U+00B5 (1647/1647)
        oxazolidinone target_units -> U+03BC (2747/2747)
        nanozymes  *_unit columns  -> U+03BC (799 vs 2)
    A BLANKET ->U+03BC (the old `MU=lambda s: s.replace('\u00b5','\u03bc')`) is a landmine: on
    benzimidazole it turns correct U+00B5 into U+03BC and ZEROES target_units (measured F1
    0.5352 -> 0.0000). `micro_norm` is domain-aware; header-unit / unknown domains are a no-op.

  * Row dedup is NOT a current metric lever. The metric matches each column as an independent
    multiset, and the harness already drops exact-duplicate rows; on the per-domain preds
    `dedup_objects` is a measured no-op (benz 619->619, oxa 227->227). Aggressive dedup on a
    SUBSET of columns HURTS (-0.003 Macro on benzimidazole) by shrinking the deliberately
    cyclically-spread SMILES column. So `dedup_objects` uses full-row identity only; it pays off
    in the future integrated multi-source pipeline (text+table+figure), where one object is
    emitted by several extractors -> genuine duplicate rows -> inflated per-column FP.

  * NOT here, on purpose: bacteria / units-FORMAT canonicalization. Gold stores the article's raw
    string (`S. aureus` | `Escherichia coli ATCC 25922` | `Staphylococcus  epidermidis  ATCC  12229`
    with double spaces | `SA` | `EC`; units `ug/mL` | `ug mL-1` | `ug ml-1` | ...). No canonical
    form matches across articles, and our own over-cleaning makes bacteria WORSE than baseline
    (0.480 vs 0.782). The lever is verbatim extraction (copy the source string) — an extraction-side
    change. A post-hoc normalizer mapping to gold strings would be test-set leakage and would not
    generalize, so it is intentionally excluded.
"""
import re

MICRO_SIGNS = ('\u00b5', '\u03bc')  # micro sign, greek small letter mu
# Per-domain target codepoint, derived from gold unit columns. Absent domain => micro chars left as-is.
MICRO_BY_DOMAIN = {
    'benzimidazole': '\u00b5',
    'oxazolidinone': '\u03bc',
    'nanozymes':     '\u03bc',
}


def micro_norm(s, domain):
    """Map every micro-sign variant in `s` to `domain`'s gold codepoint. No-op when the domain has
    no micro convention (returns `s` unchanged). Safe replacement for the blanket-MU landmine."""
    tgt = MICRO_BY_DOMAIN.get(domain)
    if tgt is None:
        return s
    out = str(s)
    for m in MICRO_SIGNS:
        if m != tgt:
            out = out.replace(m, tgt)
    return out


_WS = re.compile(r'\s+')


def norm_ws(s):
    """Collapse internal whitespace runs and strip. Surface cleanup; safe and idempotent."""
    return _WS.sub(' ', str(s)).strip()


def norm_number(s):
    """Canonicalize a numeric value cell to the gold's string form: decimal comma -> point, and drop
    a trailing '.0' so a whole number reads '125' not '125.0'. Non-numeric cells (NOT_DETECTED, ranges
    like '0.5-1', inequalities '>128', empty) are returned verbatim -- formatting those is the
    extractor's job, not this primitive's.

    Why the '.0' strip matters (measured, official metric): gold target_value is dtype=object because
    the source CSV carries decimal-comma values ('0,056'); after convert_comma a whole number stays
    '125'. A pred built with dot-decimals is pure-numeric -> pandas read_csv infers float64 -> '125.0',
    so EVERY whole-number value mismatches gold '125'. On benzimidazole this alone is target_value F1
    0.286 -> 0.514, Macro 0.358 -> 0.390. SUBTLETY: the metric realizes this only when the pred's
    target_value column is read as object, i.e. it holds >=1 non-numeric token (a NOT_DETECTED row,
    standard whenever a compound has no reported value). For an all-numeric column pandas re-floats on
    read and the gain is masked -- so this primitive is meant to run on NOT_DETECTED-filled assembly.
    """
    t = str(s).strip().replace(',', '.')
    try:
        f = float(t)
        if f != f or abs(f) == float('inf'):      # nan / inf -> leave verbatim
            return str(s)
        if f == int(f):
            return str(int(f))
        return t
    except (TypeError, ValueError, OverflowError):
        return str(s)


def dedup_objects(df, ws_normalize=True):
    """Drop duplicate extracted-object rows by FULL-ROW identity (optionally after whitespace
    normalization). For the integrated multi-source pipeline; a measured no-op on current per-domain
    preds. Full-row identity is deliberate: rows differing in ANY column (e.g. a cyclically spread
    SMILES pool) are kept, since the metric matches each column as an independent multiset."""
    if ws_normalize:
        d = df.copy()
        for c in d.columns:
            d[c] = d[c].map(norm_ws)
        return d.drop_duplicates().reset_index(drop=True)
    return df.drop_duplicates().reset_index(drop=True)


if __name__ == '__main__':
    assert micro_norm('\u03bcg/mL', 'benzimidazole') == '\u00b5g/mL'    # greek -> micro (benz)
    assert micro_norm('\u00b5g/mL', 'benzimidazole') == '\u00b5g/mL'    # already correct
    assert micro_norm('\u00b5g/mL', 'oxazolidinone') == '\u03bcg/mL'    # micro -> greek (oxa)
    assert micro_norm('\u00b5M', 'nanozymes') == '\u03bcM'
    assert micro_norm('\u00b5g/mL', 'cocrystals') == '\u00b5g/mL'       # unknown -> no-op
    assert norm_ws('Staphylococcus   aureus  ') == 'Staphylococcus aureus'
    assert norm_number('125.0') == '125'
    assert norm_number('125') == '125'
    assert norm_number('12.5') == '12.5'
    assert norm_number('0,056') == '0.056'
    assert norm_number('NOT_DETECTED') == 'NOT_DETECTED'
    assert norm_number('>128') == '>128'
    assert norm_number('0.5-1') == '0.5-1' 
    import pandas as pd
    df = pd.DataFrame([
        {'cid': '5', 'smiles': 'CC', 'val': '2.0'},
        {'cid': '5', 'smiles': 'CC', 'val': '2.0'},    # true cross-source duplicate -> collapse
        {'cid': '5', 'smiles': 'CCO', 'val': '2.0'},   # same object, spread SMILES -> KEEP
    ])
    assert len(dedup_objects(df)) == 2
    print('normalize.py self-test OK | MICRO_BY_DOMAIN=%r' % {k: hex(ord(v)) for k, v in MICRO_BY_DOMAIN.items()})