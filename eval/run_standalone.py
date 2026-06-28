"""M1: standalone answering (question-only, NO corpus). Writes answers JSONL incrementally;
resumable (skips question idx already present). Run in .venv (gateway needs anthropic):
    .venv/bin/python eval/run_standalone.py <model> <answers.jsonl> [workers] [limit]
"""
from __future__ import annotations
import csv, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/root/scinex")
from lib import llm_clients

CSV = "/root/scinex/benchmarks/_cpb/chempaperbench.csv"
SYS = ("You are a chemistry expert. Answer the question concisely and accurately from your knowledge. "
       "State key facts, numbers and units; no filler.")


def load_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try: done.add(json.loads(line)["idx"])
            except Exception: pass
    return done


def main():
    model = sys.argv[1]
    out = sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
    rows = list(csv.DictReader(open(CSV)))
    if limit: rows = rows[:limit]
    done = load_done(out)
    todo = [(i, r) for i, r in enumerate(rows) if i not in done]
    print(f"total={len(rows)} done={len(done)} todo={len(todo)} model={model} workers={workers}", flush=True)
    lock = threading.Lock(); fh = open(out, "a"); cnt = {"ok": 0, "err": 0}

    def work(item):
        i, r = item
        for attempt in range(3):
            try:
                resp = llm_clients.call(model, str(r["question"]), system_prompt=SYS, max_tokens=2000)
                rec = {"idx": i, "question": r["question"], "answer": r["answer"],
                       "level": r["level"], "category": r.get("category"),
                       "model_answer": (resp.text or "").strip(),
                       "out_tokens": (resp.usage or {}).get("output_tokens"),
                       "latency_s": round(resp.latency_s, 1)}
                with lock:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
                    cnt["ok"] += 1; t = cnt["ok"] + cnt["err"] + len(done)
                    if (cnt["ok"] + cnt["err"]) % 10 == 0:
                        print(f"  {t}/{len(rows)} (ok={cnt['ok']} err={cnt['err']})", flush=True)
                return
            except Exception as e:
                if attempt < 2: time.sleep(5 * (attempt + 1)); continue
                with lock:
                    cnt["err"] += 1
                    print(f"  ERR idx={i}: {type(e).__name__}: {str(e)[:120]}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    print(f"PHASE_A_DONE ok={cnt['ok']} err={cnt['err']}", flush=True)


if __name__ == "__main__":
    main()
