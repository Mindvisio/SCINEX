"""M2: RAG answering over the corpus index. For each question whose paper DOI is present in the
index, retrieve + (vision-)LLM answer via qa.answer. Writes answers JSONL; resumable; threaded.
Partial-corpus safe: only answers questions whose paper is in the index. Run in .venv (keys sourced):
    bash -c 'set -a; source /root/.api_keys; set +a; .venv/bin/python eval/run_rag.py <index_dir> <answers.jsonl> [model] [workers]'
Then score with: .venv-bench/bin/python eval/score_run.py <answers.jsonl> <results.csv>
"""
from __future__ import annotations
import csv, json, os, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/root/scinex")
from index.index import VectorIndex
from qa.answer import answer

CSV = "/root/scinex/benchmarks/_cpb/chempaperbench.csv"


def _canon(s):
    return re.sub(r'[^a-z0-9]', '', (s or "").lower())


def dois_of(link):
    """All DOIs in a (possibly multi-DOI) paper_link cell."""
    out = []
    for tok in re.split(r'[;,\s]+', str(link)):
        d = re.sub(r'^https?://(dx\.)?doi\.org/', '', tok).strip()
        if "10." in d:
            out.append(d)
    return out


def load_done(path):
    d = set()
    if os.path.exists(path):
        for l in open(path):
            try: d.add(json.loads(l)["idx"])
            except Exception: pass
    return d


def main():
    index_dir, out = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "claude-opus"
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    idx = VectorIndex.load(index_dir)
    have_canon = {_canon(c.paper_id) for c in idx.chunks}
    rows = list(csv.DictReader(open(CSV)))
    done = load_done(out)
    def _match(r):
        for d in dois_of(r["paper_link"]):
            if _canon(d) in have_canon:
                return d
        return None
    in_corpus = []
    for i, r in enumerate(rows):
        md = _match(r)
        if md:
            in_corpus.append((i, r, md))
    todo = [(i, r, md) for i, r, md in in_corpus if i not in done]
    print(f"corpus_papers={len(have_canon)} questions_in_corpus={len(in_corpus)} done={len(done)} todo={len(todo)} model={model}", flush=True)
    lock = threading.Lock(); fh = open(out, "a"); cnt = {"ok": 0, "err": 0}

    def work(item):
        i, r, md = item
        for att in range(3):
            try:
                a = answer(r["question"], idx, k=8, model=model)
                rec = {"idx": i, "doi": md, "question": r["question"],
                       "answer": r["answer"], "level": r["level"], "category": r.get("category"),
                       "model_answer": (a if isinstance(a, str) else getattr(a, "answer", "")),
                       "used_figures": getattr(a, "used_figures", None),
                       "confidence": getattr(a, "confidence", None),
                       "evidence": getattr(a, "evidence_paper_ids", None)}
                with lock:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush(); cnt["ok"] += 1
                    if (cnt["ok"] + cnt["err"]) % 10 == 0:
                        print(f"  {cnt['ok']+cnt['err']+len(done)}/{len(in_corpus)} (ok={cnt['ok']} err={cnt['err']})", flush=True)
                return
            except Exception as e:
                if att < 2: time.sleep(5 * (att + 1)); continue
                with lock:
                    cnt["err"] += 1; print(f"  ERR idx={i}: {type(e).__name__}: {str(e)[:100]}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    fh.close(); print(f"M2_ANSWER_DONE ok={cnt['ok']} err={cnt['err']}", flush=True)


if __name__ == "__main__":
    main()
