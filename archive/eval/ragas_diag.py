"""RAGAS-style diagnostic: re-retrieves each question's contexts from the index and scores
faithfulness / answer_relevancy / context_relevance with a gateway judge (deepseek-v4-pro). Unlike
GEval correctness (end-to-end right/wrong) this separates retrieval faults from generation faults:
low context_relevance => retrieval missed; low faithfulness => answer drifted from the evidence.
Diagnostic layer, not a leaderboard score.

usage: python eval/ragas_diag.py [N_per_level] [workers]
"""
import sys, os, csv, json, threading
sys.path.insert(0, "/root/scinex")
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, Field
from index.index import VectorIndex
from lib.llm_clients import call_json

CPB = "/root/scinex/benchmarks/_cpb"
JUDGE = "deepseek-v4-pro"


class RagasScores(BaseModel):
    faithfulness: float = Field(description="fraction of the answer's claims supported by contexts, 0..1")
    answer_relevancy: float = Field(description="how directly the answer addresses the question, 0..1")
    context_relevance: float = Field(description="fraction of retrieved contexts relevant to the question, 0..1")
    note: str = Field(default="", description="one short phrase on the main fault, if any")


_SYS = ("You are a rigorous RAG evaluator. Given a QUESTION, retrieved CONTEXTS and an ANSWER, score "
        "three metrics in [0,1] and return ONLY the JSON. faithfulness: of the factual claims in the "
        "ANSWER, the fraction directly supported by the CONTEXTS. answer_relevancy: how directly the "
        "ANSWER addresses the QUESTION. context_relevance: of the CONTEXTS, the fraction actually "
        "relevant to answering the QUESTION.")


def _context(index, question, k=8):
    out = []
    for ch, _s in index.retrieve(question, k=k):
        t = (ch.text or "").strip()
        if t:
            out.append(t[:500])
    return "\n---\n".join(out)[:3500]


def judge_row(index, row):
    ctx = _context(index, row["question"])
    prompt = ("QUESTION:\n%s\n\nCONTEXTS:\n%s\n\nANSWER:\n%s\n\nReturn JSON with faithfulness, "
              "answer_relevancy, context_relevance, note." % (row["question"], ctx, row.get("model_answer", "")))
    try:
        s = call_json(JUDGE, prompt, RagasScores, system_prompt=_SYS, temperature=0.0, max_tokens=8000).parsed
        return (s.faithfulness, s.answer_relevancy, s.context_relevance)
    except Exception:
        return None


def summarize(out_path):
    rows = list(csv.DictReader(open(out_path)))
    by = defaultdict(lambda: [[], [], []]); allm = [[], [], []]
    for r in rows:
        try:
            f, a, c = float(r["faithfulness"]), float(r["answer_relevancy"]), float(r["context_relevance"])
        except Exception:
            continue
        for i, v in enumerate((f, a, c)):
            by[r["level"]][i].append(v); allm[i].append(v)
    def m(xs):
        return sum(xs) / len(xs) if xs else float("nan")
    print("\nRAGAS diagnostic (n=%d, judge=%s)" % (len(rows), JUDGE))
    print("  overall : faithfulness %.3f | answer_relevancy %.3f | context_relevance %.3f"
          % (m(allm[0]), m(allm[1]), m(allm[2])))
    for L in sorted(by):
        b = by[L]
        print("  %-7s : faithfulness %.3f | answer_relevancy %.3f | context_relevance %.3f (n=%d)"
              % (L, m(b[0]), m(b[1]), m(b[2]), len(b[0])))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        summarize(CPB + "/_ragas.csv"); return
    n_per = int(sys.argv[1]) if len(sys.argv) > 1 else None
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    index = VectorIndex.load(CPB + "/_index")
    rows = [json.loads(l) for l in open(CPB + "/_answers.jsonl")]
    if n_per:
        by = defaultdict(list)
        for r in rows:
            by[r["level"]].append(r)
        rows = [r for L in sorted(by) for r in by[L][:n_per]]
    out_path = CPB + "/_ragas.csv"
    done = set()
    if os.path.exists(out_path):
        for r in csv.DictReader(open(out_path)):
            try:
                done.add(int(r["idx"]))
            except Exception:
                pass
    todo = [r for r in rows if r["idx"] not in done]
    print("targets %d | done %d | todo %d | judge %s" % (len(rows), len(done), len(todo), JUDGE), flush=True)
    new = not os.path.exists(out_path)
    fh = open(out_path, "a", newline=""); w = csv.writer(fh)
    if new:
        w.writerow(["idx", "level", "faithfulness", "answer_relevancy", "context_relevance"]); fh.flush()
    lock = threading.Lock(); cnt = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(lambda r: (r["idx"], r["level"], judge_row(index, r)), r) for r in todo]
        for f in as_completed(futs):
            idx, lv, sc = f.result()
            if sc is None:
                continue
            with lock:
                w.writerow([idx, lv, round(sc[0], 4), round(sc[1], 4), round(sc[2], 4)]); fh.flush()
                cnt += 1
                if cnt % 20 == 0:
                    print("  judged %d/%d" % (cnt, len(todo)), flush=True)
    fh.close(); print("RAGAS_DONE", flush=True); summarize(out_path)


if __name__ == "__main__":
    main()
