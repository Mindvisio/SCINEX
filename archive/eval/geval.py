"""ChemPaperBench G-Eval scorer — replicates ITMO's metric 1:1 for comparable numbers.

DeepEval GEval(name="Correctness") with ITMO's VERBATIM 4 evaluation steps; judge = gpt-4o-2024-08-06
via OpenRouter (DeepEval native OpenRouterModel, temperature 0). Score in [0,1]; failures -> -1
(ITMO's sentinel, excluded from the mean). score() retries with backoff to ride out OpenRouter
rate-limit bursts (the transient cause of -1 in batch runs). Needs OPENROUTER_API_KEY in env. Run:
    bash -c 'set -a; source /root/.api_keys; set +a; cd /root/scinex; .venv-bench/bin/python -m eval.geval validate 20'
"""
from __future__ import annotations
import os
import sys
import time
import httpx

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from deepeval.models.llms.openrouter_model import OpenRouterModel

JUDGE_MODEL = "openai/gpt-4o-2024-08-06"
JUDGE_MODEL_DIRECT = "gpt-4o-2024-08-06"


class ProxyOpenAIModel(OpenRouterModel):
    """gpt-4o-2024-08-06 judge via OpenAI-direct through our HTTPS proxy + our OPENAI_API_KEY.
    OpenRouter's shared gpt-4o credits are rate-limited (429) and OpenAI-direct geoblocks the RU IP
    (403); routing OpenAI-direct over LLM_PROXY with our own key fixes both. Same model snapshot ->
    comparable to ITMO's leaderboard."""
    def __init__(self, model=JUDGE_MODEL_DIRECT):
        super().__init__(model=model, base_url="https://api.openai.com/v1",
                         api_key=os.environ.get("OPENAI_API_KEY"))

    def _client_extra_kwargs(self):
        proxy = os.environ.get("LLM_PROXY")
        return {"http_client": httpx.Client(proxy=proxy, timeout=120.0)} if proxy else {}

# VERBATIM from ITMO compute_metrics.py (do NOT edit -- comparability with their leaderboard)
EVAL_STEPS = [
    "If there are numeric values in the expected output, compare the numeric values from the actual output with the"
    " corresponding values from the expected output"
    " (if at least one value is missing or incorrect (except in cases where missing numeric values do not affect "
    " the accuracy of the information provided) -> LOW SCORE, else -> HIGH SCORE)",
    "Compare textual facts regardless of the formulations used and their order"
    " (if the facts are all OK -> LOW SCORE, else -> HIGH SCORE)",
    "Estimate the amount of filler text in the actual output"
    " (if there is a lot of it -> LOW SCORE, else -> HIGH SCORE)"
    "If the actual output does not contain an answer to the INPUT or reports that it cannot answer"
    " -> VERY LOW SCORE",
]


def judge_model(api_key=None):
    return ProxyOpenAIModel()


def correctness_metric(judge=None):
    return GEval(
        name="Correctness",
        evaluation_steps=EVAL_STEPS,
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT,
                           LLMTestCaseParams.EXPECTED_OUTPUT],
        model=judge or judge_model(),
        async_mode=False,
    )


def score(question, answer, gold, metric=None, retries=4, base_delay=3.0):
    """-> (score in [0,1], reason). Retries with exponential backoff on transient errors
    (OpenRouter rate-limit/5xx). Returns (-1, last_err) only after all retries fail."""
    m = metric or correctness_metric()
    tc = LLMTestCase(input=str(question), actual_output=str(answer or ""),
                     expected_output=str(gold or ""))
    last = ""
    for attempt in range(retries):
        try:
            m.measure(tc)
            return float(m.score), (m.reason or "")
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
            if attempt < retries - 1:
                time.sleep(base_delay * (2 ** attempt))   # 3, 6, 12s
    return -1.0, last


def validate(n=20, seed=0, csv="benchmarks/_cpb/mas_rag_results.csv", pace=1.0):
    """Re-score a random sample of ITMO's mas_rag answers; compare to their geval_score."""
    import pandas as pd
    import numpy as np
    df = pd.read_csv(csv)
    df = df[pd.to_numeric(df["geval_score"], errors="coerce").notna()]
    samp = df.sample(min(n, len(df)), random_state=seed).reset_index(drop=True)
    m = correctness_metric()
    ours, theirs = [], []
    for i, r in samp.iterrows():
        s, _ = score(r["question"], r["answer_from_model"], r["answer"], metric=m)
        t = float(r["geval_score"])
        ours.append(s); theirs.append(t)
        print(f"{i:2d} L{r['level']} ours={s:.2f} theirs={t:.2f} | {str(r['question'])[:46]}")
        time.sleep(pace)
    ours, theirs = np.array(ours), np.array(theirs)
    ok = ours != -1
    print(f"\nn={int(ok.sum())}/{len(ours)} scored  mean ours={ours[ok].mean():.3f}  theirs={theirs[ok].mean():.3f}"
          f"  mean|diff|={np.abs(ours[ok]-theirs[ok]).mean():.3f}"
          f"  corr={np.corrcoef(ours[ok], theirs[ok])[0,1]:.3f}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "validate":
        validate(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    else:
        print("usage: python -m eval.geval validate [N]")
