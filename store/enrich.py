"""Figure enrichment (Eremeeva figure-JSON; figure-QA routing support). Fills AssetNode.entities
(links to canonical entity nodes named in the caption) and .data_relevance (what the figure shows)
on a BUILT CorpusStore, in place. Cheap + deterministic: caption keyword classifier + entity-name
matching against the store's entities. No API. Entities are matched in the caption AND the
figure-local surrounding text (blocks spatially adjacent to the figure, supplied by
ocr.pdf_extract as AssetNode.text) -- bounded by layout proximity, so it does not link every
entity to every figure the way a whole-paper match would.
"""
from __future__ import annotations
import re

# data_relevance tag by caption keyword; first match wins (specific -> general)
_RELEVANCE = [
    ("binding_curve", ("binding", "affinity", "dissociation constant", " kd ", "isotherm",
                       "titration", "dose-response", "dose response", "ic50", "ec50",
                       "saturation curve", "adsorption isotherm")),
    ("spectrum", ("spectra", "spectrum", "spectroscop", " nmr", "ftir", " ir ", "uv-vis",
                  "uv\u2013vis", "raman", " xrd", " xps", "diffraction", "fluorescence",
                  "absorption spectr", "mass spec")),
    ("micrograph", (" sem", " tem", " afm", " stm", "micrograph", "microscopy", "microscope")),
    ("structure", ("chemical structure", "molecular structure", "skeletal", "crystal structure",
                   "scheme", "synthesi", "reaction ")),
    ("mechanism", ("mechanism", "pathway", "catalytic cycle", "proposed")),
    ("performance_plot", ("performance", "efficiency", "yield", "conversion", "selectivity",
                          "rejection", "flux", "capacity", "cycling", "retention", "stability",
                          "as a function of", "versus", " vs ", "over time")),
    ("workflow", ("schematic", "design", "setup", "apparatus", "illustration", "overview",
                  "workflow", "fabrication", "process")),
]


def classify_data_relevance(caption: str):
    c = (caption or "").lower()
    if not c:
        return None
    for tag, kws in _RELEVANCE:
        if any(k in c for k in kws):
            return tag
    return None


def _mentions(name: str, text: str) -> bool:
    """name appears in text as a token (not flanked by alphanumerics) -- robust for chem names."""
    if not name or len(name) < 3:
        return False
    return re.search(r'(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])', text, re.I) is not None


def enrich_assets(store) -> dict:
    """Fill asset.entities (entity node_ids named in the caption) + asset.data_relevance (caption
    classifier) in place. Returns a summary {assets, entity_links, tagged}."""
    n_ent = n_tag = 0
    for a in store.assets:
        cap = a.caption or ""
        local = a.text or ""
        ctx = cap if not local else (cap + "\n" + local)    # figure-local window (caption + adjacent text)
        found = [nid for nid, e in store.entities.items()
                 if any(_mentions(nm, ctx) for nm in ([e.label] + list(e.names)) if nm)]
        a.entities = found
        a.data_relevance = classify_data_relevance(cap)
        n_ent += len(found)
        n_tag += 1 if a.data_relevance else 0
    return {"assets": len(store.assets), "entity_links": n_ent, "tagged": n_tag}


def enrich_assets_llm(store, *, model=None) -> dict:
    """LLM figure enrichment (handles abbreviations the deterministic matcher misses). Per paper,
    ONE call extracts {fig_id -> entities (canonical names, abbreviations expanded), data_relevance}
    from captions; names resolve to existing entity nodes. Falls back to the keyword classifier when
    the LLM omits data_relevance. Cheap: one call per paper, not per figure."""
    from lib.llm_clients import call_json
    from config import BULK_MODEL
    from pydantic import BaseModel, Field
    from store.build import _resolve

    class _FigTag(BaseModel):
        fig_id: str
        entities: list[str] = Field(default_factory=list)
        data_relevance: str = ""

    class _FigTags(BaseModel):
        figures: list[_FigTag] = Field(default_factory=list)

    model = model or BULK_MODEL
    tags = ("binding_curve, structure, spectrum, micrograph, performance_plot, mechanism, "
            "workflow, other")
    by_paper: dict = {}
    for a in store.assets:
        by_paper.setdefault(a.paper_id, []).append(a)
    known = sorted({e.label for e in store.entities.values()})
    for pid, assets in by_paper.items():
        figs = [{"fig_id": a.node_id, "caption": (a.caption or "")[:600], "context": (a.text or "")[:400]}
                for a in assets if a.caption]
        if not figs:
            continue
        prompt = (
            "For each figure below, from its caption identify (1) the chemical/material ENTITIES it "
            "concerns -- canonical names, expanding abbreviations (e.g. PANI->polyaniline, "
            "PA->polyamide); prefer a name from KNOWN_ENTITIES when it matches -- and (2) "
            f"data_relevance, exactly one of [{tags}].\nKNOWN_ENTITIES: {known}\n\n"
            f"FIGURES (JSON): {figs}\n\n"
            'Return ONLY {"figures":[{"fig_id":"...","entities":[...],"data_relevance":"..."}]}.'
        )
        try:
            sr = call_json(model, prompt, _FigTags, temperature=0.0, max_tokens=1500)
        except Exception:
            continue
        out = {f.fig_id: f for f in sr.parsed.figures}
        for a in assets:
            ft = out.get(a.node_id)
            if not ft:
                a.data_relevance = a.data_relevance or classify_data_relevance(a.caption)
                continue
            resolved = []
            for nm in ft.entities:
                nid = _resolve(store, nm)
                if nid and nid not in resolved:
                    resolved.append(nid)
            a.entities = resolved
            a.data_relevance = (ft.data_relevance or "").strip() or classify_data_relevance(a.caption)
    return {"assets": len(store.assets),
            "entity_links": sum(len(a.entities) for a in store.assets),
            "tagged": sum(1 for a in store.assets if a.data_relevance)}



_VTYPE2REL = {"plot": "performance_plot", "spectrum": "spectrum", "micrograph": "micrograph",
              "chemical_structure": "structure", "scheme": "mechanism", "diagram": "workflow"}


def enrich_assets_vision(store, *, model=None, max_figs=None) -> dict:
    """Read each figure crop with a vision model (default gemini-pro) and merge pixel-level signals:
    entity names seen in the figure are resolved against the store and added to asset.entities (on top
    of caption + surrounding-text links), and data_relevance is set from the figure type when the
    caption classifier left it empty. Returns {figures_read, new_entity_links, relevance_set}."""
    from ocr.figure_vision import read_figure
    assets = [a for a in store.assets if a.image_path]
    if max_figs:
        assets = assets[:max_figs]
    n_read = n_ent = n_rel = 0
    for a in assets:
        v = read_figure(a.image_path, caption=a.caption or "", model=model or "gemini-pro")
        if not v:
            continue
        n_read += 1
        vtext = " ".join(v["entities"]) + " " + v["data_summary"] + " " + v["key_finding"]
        found = [nid for nid, e in store.entities.items()
                 if any(_mentions(nm, vtext) for nm in ([e.label] + list(e.names)) if nm)]
        merged = list(dict.fromkeys(list(a.entities) + found))
        n_ent += len(merged) - len(a.entities)
        a.entities = merged
        if not a.data_relevance:
            rel = _VTYPE2REL.get(v["figure_type"].lower())
            if rel:
                a.data_relevance = rel
                n_rel += 1
    return {"figures_read": n_read, "new_entity_links": n_ent, "relevance_set": n_rel}
