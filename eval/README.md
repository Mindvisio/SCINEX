# eval — the quality story (SPEC.md section 5)

Without this, F1 is unmeasurable and the demo is just claims. Build the gold set EARLY.

## Gold set
~20 papers: 10 comp-chem (DFT/MD), 5 med-chem/longevity, 5 general.
One file per paper: eval/gold/{paper_id}.json (see _template.json). Hand-label the records
you would want extracted: entity_type + normalized (spans optional for gold).

## Scoring (eval/run_eval.py)
Match: predicted == gold iff same entity_type AND normalized-key match
  (molecule: inchikey; method: functional+basis; claim: subject+predicate+polarity;
   relation: intervention+organism+outcome).
Metric: per-type precision/recall/F1 + macro-F1.
Null baseline: naive single-shot vs verified multi-agent on the same papers -> report dF1.
Headline number for the deck = macro-F1 and dF1 over baseline.
