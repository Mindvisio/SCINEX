"""Score an answers JSONL with the ChemPaperBench G-Eval scorer; write results CSV, resumable.
Run in .venv-bench (deepeval):
    .venv-bench/bin/python eval/score_run.py <answers.jsonl> <results.csv>
"""
from __future__ import annotations
import csv, json, os, sys
sys.path.insert(0, "/root/scinex")
from eval.geval import correctness_metric, score


def load_scored(path):
    done = set()
    if os.path.exists(path):
        for row in csv.DictReader(open(path)):
            try:
                if float(row["geval_score"]) != -1:
                    done.add(int(row["idx"]))
            except Exception: pass
    return done


def summarize(res_path):
    rows = list(csv.DictReader(open(res_path)))
    def mean_for(pred):
        v = [float(r["geval_score"]) for r in rows if pred(r) and float(r["geval_score"]) != -1]
        return (sum(v) / len(v) if v else float("nan"), len(v))
    mo, no = mean_for(lambda r: True)
    print("\n=== M1 standalone G-Eval ===", flush=True)
    print(f"overall: {mo:.3f}  (n={no})", flush=True)
    for lv in ("L1", "L2", "L3"):
        m, k = mean_for(lambda r, lv=lv: str(r["level"]).strip() == lv)
        print(f"  {lv}: {m:.3f} (n={k})", flush=True)
    nf = sum(1 for r in rows if float(r["geval_score"]) == -1)
    print(f"  failed(-1, excluded): {nf}", flush=True)


def main():
    ans_path, res_path = sys.argv[1], sys.argv[2]
    answers = [json.loads(l) for l in open(ans_path) if l.strip()]
    scored = load_scored(res_path)
    metric = correctness_metric()
    fields = ["idx", "level", "category", "question", "answer", "model_answer", "geval_score", "geval_reason"]
    new = not os.path.exists(res_path)
    fh = open(res_path, "a", newline=""); w = csv.DictWriter(fh, fieldnames=fields)
    if new: w.writeheader()
    n = 0
    for rec in answers:
        i = rec["idx"]
        if i in scored: continue
        s, reason = score(rec["question"], rec["model_answer"], rec["answer"], metric=metric)
        w.writerow({"idx": i, "level": rec["level"], "category": rec.get("category"),
                    "question": rec["question"], "answer": rec["answer"],
                    "model_answer": rec["model_answer"], "geval_score": s, "geval_reason": reason})
        fh.flush(); n += 1
        if n % 10 == 0: print(f"  scored {n} new (+{len(scored)} prior)", flush=True)
    fh.close()
    print(f"PHASE_B_DONE scored {n} new", flush=True)
    summarize(res_path)


if __name__ == "__main__":
    main()
