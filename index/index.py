"""Flat vector index over a small paper corpus (no pgvector). API embeddings.

Corpus item (dict): {paper_id, doi?, title?, text (markdown),
                     figures: [{fig_id, image_path, caption}], tables: [{table_id, text}]}.
Chunks text + figure captions + tables, embeds chunk text, retrieves top-k by cosine.
Figure chunks carry image_path so qa/ can hand the image to a vision-LLM.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np

from index.embed import embed, EMBED_MODEL

_FIG_NO = re.compile(r"\bfig(?:ure)?\.?\s*(\d+)", re.I)


def _fig_no(caption: str):
    m = _FIG_NO.search(caption or "")
    return int(m.group(1)) if m else None


@dataclass
class Chunk:
    chunk_id: str
    paper_id: str
    kind: str                       # 'text' | 'figure' | 'table'
    text: str
    image_path: Optional[str] = None
    meta: dict = field(default_factory=dict)


def chunk_paper(paper: dict, max_chars: int = 1200, overlap: int = 150) -> list[Chunk]:
    pid = str(paper.get("paper_id"))
    title = paper.get("title")
    chunks: list[Chunk] = []
    text = paper.get("text", "") or ""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    buf, idx = "", 0

    def flush():
        nonlocal buf, idx
        if buf.strip():
            chunks.append(Chunk(f"{pid}:t{idx}", pid, "text", buf.strip(), meta={"title": title}))
            idx += 1

    for p in paras:
        if buf and len(buf) + len(p) + 2 > max_chars:
            flush()
            buf = buf[-overlap:] if overlap else ""
        buf += ("\n\n" if buf else "") + p
    flush()

    for f in paper.get("figures", []) or []:
        cap = (f.get("caption") or "").strip()
        fid = f.get("fig_id")
        etext = cap or ("Figure %s" % fid)
        chunks.append(Chunk(f"{pid}:fig:{fid}", pid, "figure", etext,
                            image_path=f.get("image_path"),
                            meta={"fig_id": fid, "fig_no": _fig_no(cap), "title": title,
                                  "data_relevance": f.get("data_relevance"),
                                  "entities": f.get("entities") or [], "caption": cap}))
    for t in paper.get("tables", []) or []:
        tid = t.get("table_id")
        chunks.append(Chunk(f"{pid}:tbl:{tid}", pid, "table",
                            (t.get("text") or "").strip(), meta={"table_id": tid, "title": title}))
    return chunks


@dataclass
class VectorIndex:
    chunks: list[Chunk]
    vecs: np.ndarray
    model: str = EMBED_MODEL

    def retrieve(self, query: str, k: int = 8) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        qv = np.asarray(embed([query], model=self.model)[0], dtype=np.float32)
        qv /= (np.linalg.norm(qv) + 1e-8)
        sims = self.vecs @ qv
        order = np.argsort(-sims)[:k]
        return [(self.chunks[int(i)], float(sims[int(i)])) for i in order]

    def save(self, path: str) -> None:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        np.save(p / "vecs.npy", self.vecs)
        (p / "chunks.json").write_text(json.dumps([asdict(c) for c in self.chunks], ensure_ascii=False))
        (p / "meta.json").write_text(json.dumps({"model": self.model}))

    @classmethod
    def load(cls, path: str) -> "VectorIndex":
        p = Path(path)
        vecs = np.load(p / "vecs.npy")
        chunks = [Chunk(**c) for c in json.loads((p / "chunks.json").read_text())]
        meta = json.loads((p / "meta.json").read_text())
        return cls(chunks=chunks, vecs=vecs, model=meta.get("model", EMBED_MODEL))


def build_index(corpus: list[dict], model: str = EMBED_MODEL) -> VectorIndex:
    chunks: list[Chunk] = []
    for paper in corpus:
        chunks.extend(chunk_paper(paper))
    vecs = np.asarray(embed([c.text for c in chunks], model=model), dtype=np.float32)
    if vecs.size:
        vecs /= (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-8)
    return VectorIndex(chunks=chunks, vecs=vecs, model=model)
