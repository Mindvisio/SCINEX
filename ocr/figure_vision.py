"""Gemini-vision figure reader: read a figure crop directly (pixels, not just caption) ->
structured {figure_type, entities, data_summary, key_finding}. Strengthens the multimodal path --
entities and figure type come from what the figure SHOWS, beyond caption text and DECIMER skeletal
SMILES. Uses the gateway vision channel (default gemini-3.1-pro, strong multimodal); any
vision-capable alias works.
"""
from __future__ import annotations
import json

_PROMPT = (
    "Look at this scientific figure and report what it shows. Return ONLY a JSON object, no prose, "
    "no markdown fences:\n"
    '{"figure_type": "<plot|chemical_structure|micrograph|scheme|diagram|spectrum|other>",\n'
    ' "entities": ["<chemical / material / biological names shown or labeled; atom labels too>"],\n'
    ' "data_summary": "<for plots: axes + trend + key numeric values; else a short description of '
    'what is depicted>",\n'
    ' "key_finding": "<one sentence: what the figure demonstrates>"}'
)


def _parse_json(txt):
    txt = (txt or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
    a, b = txt.find("{"), txt.rfind("}")
    if a < 0 or b < 0:
        return None
    try:
        return json.loads(txt[a:b + 1])
    except Exception:
        return None


def read_figure(image_path, *, caption="", model="gemini-pro", timeout=120):
    """Read a figure image -> {figure_type, entities(list), data_summary, key_finding}, or None."""
    from lib.llm_clients import call_vision, LLMError
    prompt = _PROMPT + (("\nCaption for context: " + caption[:300]) if caption else "")
    try:
        r = call_vision(model, prompt, [image_path], max_tokens=4000, temperature=0.0, timeout=timeout)
    except LLMError:
        return None
    d = _parse_json(r.text)
    if not d:
        return None
    ents = d.get("entities") or []
    if not isinstance(ents, list):
        ents = [str(ents)]
    return {"figure_type": str(d.get("figure_type") or ""),
            "entities": [str(e) for e in ents],
            "data_summary": str(d.get("data_summary") or ""),
            "key_finding": str(d.get("key_finding") or "")}
