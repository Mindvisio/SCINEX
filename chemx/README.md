# ChemX / DataCon26 — Benzimidazole extraction

**Result:** Macro-F1 **0.384** over all 9 official OA articles (**0.494** over the 7 with obtainable PDFs) vs single-agent baseline **0.217**. Beaten on every one of the 7 fields.

## Winning pipeline
PDF -> Mathpix OCR (`pdf_to_markdown`, structured pipe-tables) -> `focus()` (table blocks + legend/abbrev context) -> deepseek-v4-pro / gemini-pro JSON extraction (compound_id, target_type, target_relation, target_value, target_units, bacteria) -> OCSR SMILES pool (MolScribe+DECIMER) attached cyclically to rows (metric bags columns independently, so SMILES need only be the right *set*).

## Files
- `scripts/extract_all.py` — Mathpix->deepseek extractor (main, 0.494)
- `scripts/extract_compare.py` — Mathpix vs Tabula head-to-head on gemini
- `scripts/score9.py` — official 9-article scoring; `score_final.py` — 7-article + OCSR
- `scripts/metric_local.py` — faithful copy of ChemX metric_calc, reproduces 0.2170 baseline exactly
- `scripts/dl_benz*.py` — PDF downloaders (Unpaywall / Europe PMC ?pdf=render)
- `results/llm_*.json` — extracted rows per paper; `results/chem_db.dedup.csv` — OCSR structures
- `pdfs/` — 7 of 9 OA PDFs (gitignored). Missing (unobtainable): 2023.12.si5a.0471, rjc.2023.1638382

## Metric (verified)
Macro = mean F1 over 7 fields; per-field tp/fp/fn pooled across articles (micro within field, macro across fields); **each column matched independently as a multiset**. 9 OA articles, 456 rows.

## Reproduce
`.venv-eval/bin/python chemx/scripts/score9.py`  (needs /tmp/chemx_benz results or copy from results/)

## Findings (OCR/table layer)
- Mathpix structured markdown -> LLM is the strongest table input (beats raw Tabula/Camelot grid on wide multi-assay tables).
- Tabula/Camelot == Mathpix on SIMPLE text tables (exact text, free, local); break on wide tables -> need column-trim.
- DeepSeek-OCR: hallucinates dense grids — rejected.
- Marker (surya): handles raster+text, but ~37min/table on CPU -> 3080 only.
- smiles field is the one weak spot (0.05): benzimidazole = SAR series (78 cmpd / 8 scaffolds) -> needs scaffold OCSR + R-group enumeration, not per-crop OCSR.
