"""Route a figure-referencing question to the most relevant figure crop(s) -- index-only.

qa.answer uses this to FORCE-include the right figure image in the vision call even when the
caption-text cosine retrieval missed it. Figure questions are ~2/3 of ChemPaperBench (hits L2/L3).

Signals (all from figure-chunk meta, baked at index build):
  explicit  -- question cites "Figure N"/"Fig. N"/"Scheme N" and meta.fig_no matches   (decisive)
  type      -- question's data_relevance (same classifier) == meta.data_relevance        (strong)
  entities  -- distinctive terms shared between question and caption / linked entities    (supporting)
Conservative: with no figure signal at all, returns [] (text retrieval handles those).
"""
from __future__ import annotations
import re
from store.enrich import classify_data_relevance

_REF = re.compile(r"\b(?:fig(?:ure)?|scheme)\.?\s*(\d+)", re.I)
_FIG_WORD = re.compile(
    r"\b(fig(?:ure)?|scheme|panel|image|micrograph|spectrum|spectra|curve|plot|graph|"
    r"shown|depicted|inset|photograph|diagram|illustrat)\b", re.I)
_STOP = {"the","a","an","of","in","on","for","to","and","or","is","are","was","were","what",
         "which","how","does","do","with","by","at","as","from","that","this","these","those",
         "its","their","between","based","figure","fig","scheme","panel","image","value",
         "values","shown","using","used","into","than","then","also","can","be","it","effect"}


def _q_refs(q: str):
    return {int(m.group(1)) for m in _REF.finditer(q or "")}


def _terms(s: str):
    return {w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", (s or "").lower()) if w not in _STOP}


def route_figures(question: str, figure_chunks, *, max_figures: int = 3, top_paper=None):
    """Rank figure Chunks for a question; return best-first crops to force into the vision call."""
    if not figure_chunks:
        return []
    refs = _q_refs(question)
    q_type = classify_data_relevance(question)
    q_terms = _terms(question)
    fig_intent = bool(refs) or bool(q_type) or _FIG_WORD.search(question or "") is not None
    if not fig_intent:
        return []
    scored = []
    for ch in figure_chunks:
        m = getattr(ch, "meta", None) or {}
        s = 0.0
        if refs and m.get("fig_no") in refs:
            s += 100
        if q_type and m.get("data_relevance") == q_type:
            s += 25
        cap_terms = _terms(m.get("caption") or getattr(ch, "text", ""))
        ent_terms = set()
        for e in (m.get("entities") or []):
            ent_terms |= _terms(e)
        shared = q_terms & (cap_terms | ent_terms)
        s += min(len(shared) * 4, 20)
        if s == 0:
            continue
        if top_paper and getattr(ch, "paper_id", None) == top_paper:
            s += 3
        if m.get("data_relevance") in ("performance_plot", "binding_curve", "spectrum"):
            s += 2
        scored.append((s, ch))
    scored.sort(key=lambda x: -x[0])
    return [ch for _s, ch in scored[:max_figures]]
