"""Normalized OCR confidence contract.

Mistral OCR 4 and Mathpix emit confidence in DIFFERENT shapes; this unifies them so the
QA-gate / review-queue consumes one structure regardless of engine.

EMPIRICAL SHAPES (verified):
  Mistral OCR 4 -> page['confidence_scores'] = {
      word_confidence_scores: [{text, confidence, start_index}],   # per-WORD
      average_page_confidence_score, minimum_page_confidence_score}
  Mathpix /v3/text (include_line_data=True) -> {
      confidence,        # JOINT prob whole region 100% correct (drops with length; NOT a quality rate)
      confidence_rate,   # per-char correctness (~quality; the comparable-to-Mistral-avg number)
      line_data: [{type, text, confidence, confidence_rate, is_printed}]}  # per-LINE

Normalization rule: page_confidence/min use Mistral's avg/min and Mathpix's confidence_rate
(NOT Mathpix's joint `confidence`, which is kept as raw_overall for reference only).
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field


class ConfToken(BaseModel):
    text: str
    confidence: float                       # 0..1 (Mathpix: the line's confidence_rate)
    kind: Literal["word", "line"]
    page: Optional[int] = None


class OCRConfidence(BaseModel):
    engine: str
    page_confidence: float                  # representative per-page quality (avg / per-char rate)
    min_confidence: float                   # weakest token on the page
    tokens: list[ConfToken] = Field(default_factory=list)
    raw_overall: Optional[float] = None      # Mathpix joint `confidence` (no Mistral analog)


def low_conf(conf: OCRConfidence, threshold: float = 0.92) -> list[ConfToken]:
    """Tokens below threshold -> review-queue / gate. 0.92 default per OCR-project practice."""
    return [t for t in conf.tokens if t.confidence < threshold]


def from_mistral_page(page: dict, page_idx: Optional[int] = None) -> OCRConfidence:
    cs = page.get("confidence_scores") or {}
    toks = [ConfToken(text=w.get("text", ""), confidence=float(w.get("confidence", 0.0)),
                      kind="word", page=page_idx)
            for w in (cs.get("word_confidence_scores") or [])]
    return OCRConfidence(
        engine="mistral",
        page_confidence=float(cs.get("average_page_confidence_score") or 0.0),
        min_confidence=float(cs.get("minimum_page_confidence_score") or 0.0),
        tokens=toks)


def from_mathpix_text(resp: dict, page_idx: Optional[int] = None) -> OCRConfidence:
    rates = []
    toks = []
    for ln in (resp.get("line_data") or []):
        cr = ln.get("confidence_rate")
        if cr is None:                       # structural line (column/page_info) -> skip
            continue
        toks.append(ConfToken(text=(ln.get("text") or "").strip(), confidence=float(cr),
                              kind="line", page=page_idx))
        rates.append(float(cr))
    page_conf = resp.get("confidence_rate")
    page_conf = float(page_conf) if page_conf is not None else (sum(rates) / len(rates) if rates else 0.0)
    return OCRConfidence(
        engine="mathpix",
        page_confidence=page_conf,
        min_confidence=min(rates) if rates else 0.0,
        tokens=toks,
        raw_overall=resp.get("confidence"))



def from_mathpix_lines(line_list, page_idx=None):
    """OCRConfidence from pdf_to_lines() output (v3/pdf lines.json: flat per-line list with
    confidence_rate). Same normalization as from_mathpix_text (per-char rate; joint conf ignored)."""
    rates, toks = [], []
    for ln in (line_list or []):
        cr = ln.get("confidence_rate")
        if cr is None:
            continue
        toks.append(ConfToken(text=(ln.get("text") or "").strip(), confidence=float(cr),
                              kind="line", page=ln.get("page", page_idx)))
        rates.append(float(cr))
    return OCRConfidence(
        engine="mathpix",
        page_confidence=(sum(rates) / len(rates)) if rates else 0.0,
        min_confidence=min(rates) if rates else 0.0,
        tokens=toks)
