"""Mode B: question -> index.retrieve(text+figures) -> (vision-)LLM answer -> typed BenchAnswer.

Two-step: (1) the answer model reasons over context+figures and writes a free-text answer
(full reasoning preserved — forcing JSON on Claude would disable thinking, hurting L2/L3);
(2) a cheap structuring pass (call_json) extracts the typed BenchAnswer (quantities/confidence)
WITHOUT rewording the answer. evidence_paper_ids/used_figures come from retrieval, not the model.
structured=False returns plain text (fast path for pure G-Eval scoring).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pydantic import BaseModel, Field

from index.index import VectorIndex
from qa.figure_router import route_figures
from lib import llm_clients

ANSWER_MODEL = "claude-opus"          # vision-capable; "gpt-5.5-pro"/"gemini-pro" alternates
STRUCTURING_MODEL = "deepseek-v4-pro" # cheap/fast text model for the structuring pass

SYS = ("You are a careful scientific assistant answering questions about research papers. "
       "Use ONLY the provided context (text excerpts, tables, and figure images). Be precise "
       "with numbers, units, and named entities; read figures when needed. If the context does "
       "not contain the answer, say so briefly. Answer directly, no filler.")


class Quantity(BaseModel):
    name: str = ""
    value: float
    unit: str = ""


class BenchAnswer(BaseModel):
    answer: str                                              # NL answer (scored by G-Eval)
    quantities: list[Quantity] = Field(default_factory=list) # structured numerics (L2 calc/multimodal)
    confidence: float = 0.5
    evidence_paper_ids: list[str] = Field(default_factory=list)
    used_figures: bool = False


_STRUCT = ("You convert an existing answer into structured JSON. Copy the ANSWER TEXT verbatim "
           "into 'answer'. Extract every explicit numeric result into 'quantities' as "
           "{name, value, unit}. Set 'confidence' 0..1 for how directly the answer addresses the "
           "question. Do not reword the answer.")


def answer(question: str, index: VectorIndex, *, k: int = 8,
           model: str = ANSWER_MODEL, max_figures: int = 3,
           max_tokens: int = 1500, structured: bool = True):
    """Retrieve top-k, answer with a (vision-)LLM, then optionally structure into BenchAnswer."""
    hits = index.retrieve(question, k=k)
    # papers surfaced by text retrieval; scope figure routing to them (a question targets one paper)
    hit_papers: list[str] = []
    for ch, _s in hits:
        pid = getattr(ch, "paper_id", None)
        if pid and pid not in hit_papers:
            hit_papers.append(pid)
    fig_pool = [c for c in index.chunks if c.kind == "figure" and c.paper_id in set(hit_papers)]
    routed = route_figures(question, fig_pool, max_figures=max_figures,
                           top_paper=hit_papers[0] if hit_papers else None)

    parts: list[str] = []
    images: list[str] = []
    papers: list[str] = []
    seen: set = set()
    for ch in routed:                                    # routed crops first -> forced into vision
        if ch.image_path and ch.image_path not in seen and len(images) < max_figures:
            images.append(ch.image_path); seen.add(ch.image_path)
            parts.append(f"[{ch.text}]")
            if ch.paper_id not in papers:
                papers.append(ch.paper_id)
    for ch, _score in hits:
        pid = getattr(ch, "paper_id", None)
        if pid and pid not in papers:
            papers.append(pid)
        if ch.kind == "figure":
            if ch.image_path and ch.image_path not in seen and len(images) < max_figures:
                parts.append(f"[{ch.text}]"); images.append(ch.image_path); seen.add(ch.image_path)
        else:
            parts.append(ch.text)
    context = "\n\n---\n\n".join(p for p in parts if p)
    prompt = f"CONTEXT:\n{context}\n\nQUESTION: {question}\n\nANSWER:"

    if images:
        r = llm_clients.call_vision(model, prompt, images, system_prompt=SYS,
                                    max_tokens=max_tokens, reasoning_effort="medium")
    else:
        r = llm_clients.call(model, prompt, system_prompt=SYS,
                             max_tokens=max_tokens, reasoning_effort="medium")
    raw = (r.text or "").strip()
    if not structured:
        return raw

    sp = f"QUESTION: {question}\n\nANSWER TEXT:\n{raw}"
    try:
        ba = llm_clients.call_json(STRUCTURING_MODEL, sp, BenchAnswer,
                                   system_prompt=_STRUCT, max_tokens=4000).parsed
        ba.answer = raw                       # enforce verbatim (G-Eval scores this field)
    except llm_clients.LLMError:
        ba = BenchAnswer(answer=raw)          # structuring failed -> never lose the answer
    ba.evidence_paper_ids = papers[:5]
    ba.used_figures = bool(images)
    return ba


if __name__ == "__main__":
    # standalone structuring smoke (no index): Q + answer -> BenchAnswer
    sp = ("QUESTION: What pore size gave best Li selectivity, and the Mg rejection rate?\n\n"
          "ANSWER TEXT:\nThe 0.57 nm pore size gave the best selectivity, with a Mg2+ "
          "rejection of 96% and a water flux of 12.3 L/m2/h.")
    ba = llm_clients.call_json(STRUCTURING_MODEL, sp, BenchAnswer, system_prompt=_STRUCT, max_tokens=4000).parsed
    print("answer  :", ba.answer)
    print("quants  :", [(q.name, q.value, q.unit) for q in ba.quantities])
    print("conf    :", ba.confidence)
