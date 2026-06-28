# M2 — RAG scored run (ChemPaperBench)

**Date:** 2026-06-25  **Corpus:** 53 uploaded papers → index 5018 chunks (4102 text / 795 figure / 121 table).
**Answerable:** 314/376 questions (L1 188 / L2 79 / L3 47) via canonical multi-DOI matching (53/101 papers present).
**Pipeline:** VectorIndex retrieval → figure-question routing (`qa.figure_router`) → Opus-vision answer (`qa.answer`) → `call_json` structuring.
**Judge:** DeepEval GEval Correctness, `gpt-4o-2024-08-06` OpenAI-direct via LLM_PROXY (ITMO-comparable snapshot).

## Scores (G-Eval, valid n=313)
| level | scinex | ITMO MAS-RAG | M1 (Opus standalone) |
|---|---|---|---|
| overall | **0.799** | 0.650 | 0.590 |
| L1 | 0.790 (n=187) | 0.699 | — |
| L2 | 0.834 (n=79) | 0.623 | — |
| L3 | 0.772 (n=47) | 0.502 | — |

Every level above the ITMO MAS-RAG reference; overall +0.149 over target, +0.209 over M1.

## Figure routing (OBSERVATIONAL — not causal)
64% of answers used a routed crop. `used_figures=True` 0.815 (n=200) vs `False` 0.770 (n=113).
By level: L1 0.815 vs 0.745 · **L2 0.829 vs 0.843 (no clean figure advantage at its target level)** · L3 0.785 vs 0.752.
→ Correlation, confounded by question type. Routing's causal effect needs an on/off **ablation**.

## Caveats
- Over 314 answerable questions (53/101 papers), NOT the full 376 — not 1:1 with ITMO's leaderboard.
- Plain build: routing used `fig_no` + `data_relevance` only; no entity-label signal (`--store --enrich-llm`).
- M1 0.590 was Opus *standalone* (no retrieval) — most of the +0.209 is retrieval, not specifically routing.
