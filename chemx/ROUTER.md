# scinex smiles router

Production routing for the smiles column. Two axes: **which strategy** per paper, and **which model** per task. Implemented in `chemx/smiles_router.py` (runs in `.venv-lite`, which has llm_clients + rdkit + py2opsin).

## Level 1 - strategy per paper  (`classify_strategy`)
Cheap rule-based classifier on the OCR (optionally confirmed by DeepSeek for ambiguous cases):

| signal | strategy | why |
|--------|----------|-----|
| explicit systematic names dense in experimental (`_IUPAC_RE` >= 15 hits) | **IUPAC -> OPSIN** | deterministic, exact. Won oxazolidinone (smiles 0.000 -> 0.493, molecules paper 17/17 exact). |
| trivial drug names in a name column | **name -> PubChem** | PUG REST IsomericSMILES. Won cocrystals (drug 0 -> 0.637). |
| figure-only compounds (labels like 5a, no names) | **OCSR ensemble** | fallback; structures live only in drawings. |

Order of preference: OPSIN > PubChem > OCSR. OPSIN/PubChem are exact when applicable; OCSR is the frontier-limited fallback.

## Level 2 - OCSR ensemble  (`ocsr_ensemble_pool` + `union_clean`)
For figure-only papers. Merge complete-core structures from every engine, dedup:

| engine | cost | role | when |
|--------|------|------|------|
| **MolScribe** (.venv-chem) | free/local | full-page + figure-region OCSR | ALWAYS (base) |
| **DECIMER** (.venv-decimer) | free/local | second specialized OCSR, complementary | ALWAYS (base) |
| **Claude-opus** vision (llm_clients) | paid, ~30-90s/3pg | **PRIMARY** vision OCSR (antibiotics 26/57, intechopen 2/4) | always |
| MolScribe + DECIMER | free/local | base, add ~2 disjoint | always |
| ~~Gemini-3.1 / GPT-5.5~~ | paid | DROPPED: Gemini adds 0 marginal gold + dilutes (F1 0.161->0.120); GPT-5.5 0 yield | not used |

Use full-PAGE batch prompts for VLMs (JSON `[{label,smiles}]`), never per-crop (per-crop = 35-117 s/call, full-page = ~12 s/3 pages). Always complete-core filter VLM output or it floods the pool with false positives (Gemini gave 207 structures for 2 gold hits on antibiotics).

**Validated ensemble (antibiotics10081002, gold 57):** MolScribe 1 + DECIMER 3 + Gemini 2 (disjoint) = **5 unique**, smiles-F1 0.0052 -> 0.0260 (+DECIMER) -> **0.0364** (+Gemini). Marginal but strictly monotone. intechopen bis-heterocycles: 0/4 across all engines = real OCSR frontier.

## Level 3 - text tasks (rows / R-tables / name extraction)
| model | role |
|-------|------|
| **DeepSeek-direct** | fast/cheap workhorse: strategy classification, high-volume measurement-row extraction, R-table parsing. The default for bulk text. |
| **Claude-opus** | hard/critical extraction. Nailed oxazolidinone rows (molecules 68 rows / 17 cmpds exact) and IUPAC name pull (17/17). Use when DeepSeek is not enough. |
| Gemini-pro | alternate text channel / cross-check. |

## GPT-5.5-Pro verdict
Tested twice as vision OCSR (antibiotics pages): `reasoning_effort='low'` is rejected by the model (400); with `medium` it ran 86 s and returned 0 usable structures. Slow + API friction + zero yield here. **Keep it out of the production hot path**; revisit only as an optional experimental engine. The OCSR ceiling is already confirmed across three engines (MolScribe, DECIMER, Gemini) - adding a fourth frontier VLM is not where the smiles gains are. The real lever is Level-1 strategy matching (OPSIN/PubChem), not more OCSR engines.

## Routing principle
Free local first (MolScribe+DECIMER) -> adaptive single-VLM escalation (Gemini) only when the local pool is sparse -> max-effort (Claude) reserved for the hardest cases. Never fan out to all VLMs blindly: gains are marginal and additive, costs and false-positive noise are not.

## Infra note
llm_clients now runs on the 3080 (`.venv-lite`, keys at `/home/ubuntu/.api_keys`, KEYS_FILE auto-detects). Frontier APIs reach through the same US proxy the voice-trainer uses (`77.47.241.198:50100`) - the 3080 IP is already allowlisted and the port is open, so no geo-block. The whole smiles pipeline (OCSR engines + VLM + OPSIN/PubChem) can therefore run on the 3080 in one place.

## Where the heavy OCSR packages sit (the conveyor)
We installed a full specialized stack; this is each package's stage + honest status.

```
Stage 0  INGESTION   pdf -> text/figures   (ROUTED by ocr/dispatch.py, confidence-gated)
  route = force_engine or ("mistral" if scanned else ("mathpix" if math_tables else "pymupdf"))
  pymupdf4llm [ocr/pdf_extract]        USED   default: text-layer PDFs, fast/free
  Mathpix     [ocr/mathpix]            USED   formula->LaTeX + tables, 5000 pg/mo; also the
                                              escalation target when Mistral confidence is low
  Mistral OCR [ocr/mistral_ocr]        USED   scanned/no-text; per-word confidence + figure bboxes
                                              (bboxes also feed Stage 1 localization)
    confidence gate: Mistral min-word-conf < GATE -> re-run Mathpix (engine "mistral->mathpix")
  always keep PyMuPDF figure crops (vision edge -> Stage 1/2 OCSR)
  GROBID / JATS / HTML full-text [ocr/grobid,jats_extract,html_extract]  available (OA XML path)
  Marker [.venv-marker]                INSTALLED, DEFERRED  (local structure/table-dense fallback)
  NOTE: OCR backend is chosen per paper and matters for strategy -- OPSIN needs pristine systematic
        names, so formula/scan papers must hit Mathpix/Mistral, not pymupdf. Provenance confirms the
        router already split benzimidazole papers across Mathpix vs mistral/pymupdf by type.

Stage 1  DETECTION   page -> molecule regions
  OpenChemIE moldet [.venv-chem]       USED  (runs inside extract_molecules_from_figures, on rendered pages + embedded figures)
  decimer-segmentation [.venv-decimerseg] USED (alt cropper; handles vector PDFs by rendering, feeds DECIMER)

Stage 2  OCSR        structure -> SMILES   (= router Level 2 ensemble)
  OpenChemIE MolScribe [.venv-chem]    USED  (base engine)
  DECIMER [.venv-decimer]              USED  (complementary)
  Gemini-3.1-Pro vision                USED  (frontier escalation)
  (MolNexTR                            NOT installed; candidate stronger OCSR)

Stage 3  COREF       SMILES -> correct compound_id
  OpenChemIE coref                     INSTALLED, IDLE  <-- highest-value unused lever
    extract_molecule_corefs_from_figures_in_pdf links each read structure to its label,
    replacing the current blind 'cycle dedup pool into all rows'. Direct fix for smiles<->compound_id
    assignment + precision. Won't beat the OCSR ceiling on unreadable structures, but tightens
    everything that IS read.

Stage 4  R-TABLES / REACTIONS
  OpenChemIE tableextractor            INSTALLED, IDLE  (R-group tables; today done via claude-opus)
  OpenChemIE RxnScribe [.venv-chem]    INSTALLED, IDLE  (reaction schemes; irrelevant for benzimidazole,
                                                         load-bearing for reaction-bearing domains)
```

**Summary:** the detection+OCSR core (OpenChemIE moldet+MolScribe, DECIMER) is load-bearing and properly wired into the Level-2 ensemble. What is installed but idle is the layer ON TOP of OCSR: coref (structure<->label), native table extraction (R-groups), RxnScribe (reactions), and Marker (ingestion). Of these, **coref is the concrete next lever for the smiles column**; RxnScribe/tables become load-bearing once we extend scinex past benzimidazole to reaction/Markush-heavy domains.

## Orchestrator built + tested (pipeline_graph.py)
Decision graph over the existing tools; every node logs {decision, why, evidence} = the reasoning trace.
Nodes: N0 doc_type(pdf|web) -> N1 classify_pdf(scanned vs digital; embedded-fig count; vector flag) ->
N2 ingest(ocr.dispatch: pymupdf|Mathpix|Mistral+conf) -> N3 figures(vector->raster: rasterize pages
for OCSR) -> N4 strategy(OPSIN|PubChem|OCSR + OCR<->strategy coupling) -> N5 run(OPSIN/PubChem/ensemble)
-> N6 coref[3080, hooked] -> N7 gates(confidence+completeness). Reactions intentionally OUT.

### End-to-end test (real PDFs, smiles-F1 vs gold)
| paper | kind | strategy | orchestrator | OCSR-only | note |
|-------|------|----------|--------------|-----------|------|
| acsomega.2c06142 | digital | opsin | **0.4444** | 0.0000 | strategy router PROVES out: names OPSIN recovered structures no OCSR engine read |
| antibiotics10081002 | digital | opsin | 0.0312 | 0.0364 | review w/ template names: opsin slightly DILUTED the pool -> classifier needs precision |
| intechopen.108949 | digital(vector!) | opsin | 0.0000 | 0.0000 | vector detected (0 embedded, 11 vec-pages -> raster); bis-heterocycle OCSR ceiling holds |

### Validated
- N1 scanned-vs-digital gate + **vector detection** (intechopen: embedded=0, vec_pages=11 -> vector_figures=True) work.
- N2 OCR routing via ocr.dispatch works (all 3 digital -> pymupdf, correct).
- **Strategy routing has real, large value**: acsomega 0 -> 0.444. This is the Level-1 lever, confirmed end-to-end - bigger than any OCSR-engine add.
- union_clean keeps OCSR pool even on opsin papers -> robust to misclassification.

### Findings to fix (next)
1. classify_strategy OVER-selects opsin on review papers (high name density != clean per-compound names). antibiotics regressed 0.0364->0.0312. Fix: gate opsin enrichment on parse-rate / per-compound name presence; or keep OCSR pool primary and only ADD opsin names that pass the core filter without displacing.
2. smiles_opsin (claude-opus) can hang on some papers (d2ra ran >7 min on one call; call_json timeout not enforced on this path). Fix: hard subprocess timeout + fallback to OCSR.
3. N6 coref still hooked-not-run (assign SMILES<->compound_id) -- next activation.

## Where the moat is (Claude-vision is a commodity -- the router must win elsewhere)
Empirical: on acsomega.2c06142 Claude-vision ALONE = 7/7 gold = smiles-F1 0.4444, IDENTICAL to our OPSIN
strategy. Anyone can call claude-opus vision and get the smiles structures. So the smiles column is NOT
our edge. The edge is the engineering around it that a naive Claude-vision call lacks, and it lives in
the OTHER 6 columns + cross-domain robustness:

- **Measurement-row extraction** (target_value / target_relation / target_units = 3 of 7 columns).
  oxazolidinone end-to-end: target_value 0.264->0.929 (our table read), units 0.000->0.980. These, not
  smiles, drove Macro 0.49->0.83.
- **Normalization levers** (pure engineering, competitors miss): units micro-sign Unicode +0.115;
  pdf-key alphanumeric match (nanozymes 0/39 articles -> matched, +0.167); name canonicalization.
- **Multiset assembly discipline**: row-count control so precision is not capped by over-production
  (the 0.4444 ceiling on acsomega is exactly this -- a competitor dumping rows scores worse).
- **coref assignment**: right SMILES on the right compound_id (Claude-vision only yields a pool).
- **OCR routing** (Mathpix/Mistral per paper) -> clean tables -> correct value/units; pymupdf-only loses.
- **Per-document decision graph**: scanned/vector/names/figures, confidence gates, vector->raster.

Strategy: do NOT over-invest in the smiles/vision arms race (commodity). Invest in the deterministic +
normalization + assembly layers that cover all columns and are hard to replicate. Claude-vision is ONE
commodity component inside a router whose value is the orchestration.

## Converged OCSR-pool convention + integration (one source of truth)
**One file per paper:** `ocsr_pool_<paper>.json` = `{pdf, pages, pool, scaffolds, engines}`.
- `engines` = `{molscribe, decimer, claude_vision}` -- each a list of `{smiles}`. The single place all
  OCSR engines land. **Gemini excluded by design** (0 marginal gold + dilutes).
- `pool` / `scaffolds` (legacy, parallel `smiles_enrich_all.py` reads `scaffolds`) left UNTOUCHED.
- Producer side: `ocsr_extract.py` (MolScribe) should write `engines.molscribe`; DECIMER/Claude stages
  write `engines.decimer` / `engines.claude_vision`. `converge_pools.py` migrates existing outputs
  (idempotent). Consumer: `smiles_router.ocsr_ensemble_pool` reads `engines` (preferred) with flat
  per-engine files (`molscribe_/figpool_/decimer_raw_/claudepg_`) as fallback -> robust to a regen race.
- Validated post-converge: antibiotics 28/57 smiles-F1 0.1662 (parallel MolScribe is fuller -> +0.005),
  intechopen 2/4, acsomega 7/7.

## Normalization wired (it measurably helped)
`smiles_router.normalize_pred(df, domain)` calls the parallel track `chemx/scripts/normalize.py`:
domain-aware `micro_norm` on `target_units` (benz U+00B5, oxa/nanozymes U+03BC -- the global MU was a
mine) + safe full-row `dedup_objects`. Applied at pred-assembly. We import their module, never edit it.

## Mathpix bbox + line-confidence (incoming from OCR track)
Mathpix `v3/text include_line_data` yields per-line `cnt` bbox + block type (text/math/eq_number) +
line confidence -- closing the Mathpix confidence gap. Router consumes it for free: N2 already pulls
`confidence` from `ocr.dispatch` and N7 gates on it (lights up once the OCR track wires Mathpix into
dispatch); the `cnt` bbox + math/text split become an extra Stage-1 figure/formula localizer.

## CORRECTION: coref (N6) tested -- does NOT help our gold; do not wire for the competition
Ran the existing ocr/openchemie_worker._coref (extract_molecule_corefs) on 3 papers:
| paper | molecules | labeled | correct compound_id<->smiles |
|-------|-----------|---------|------------------------------|
| antibiotics10081002 (review) | 176 | 70 | 1/57 |
| acsomega.2c06142 (primary)   | 61  | 12 | 0/8  |
| d2ra06667j (primary)         | 54  | 10 | 0/67 |

Why it fails: benzimidazole SAR papers draw a SCAFFOLD + a SERIES label ("5a-h", "2a-2n") + an R-table.
coref links scaffold<->series-label (often garbled OCR of the R-table header), but the gold compound_ids
are the ENUMERATED variants (5a, 3g, 28b). coref does not enumerate; enumeration is exactly what the LLM
R-enrichment (enrich_chunked: scaffold + R-table -> {compound_id: R fragment}) already does, yielding
per-id SMILES directly. So coref is redundant + near-zero here. N6 stays a disabled hook.
Platform-later: coref helps only on papers that draw each compound FULLY with an INDIVIDUAL label
(not scaffold+series). The real compound_id<->smiles assignment for our domains comes from R-enrichment.
