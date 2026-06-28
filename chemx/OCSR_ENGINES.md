# OCSR engine experiment: DECIMER vs MolScribe on smiles=0 benzimidazole papers

Goal: lift smiles on papers where MolScribe (OpenChemIE) yields ~0 (complex fused structures).
Pipeline: decimer-segmentation (Mask R-CNN, crop individual molecules per page @300dpi) -> DECIMER 2.8 (transformer OCSR) per crop -> RDKit canonical + complete-core filter.

## Per-paper gold overlap (unique correct structures captured)
| paper | gold uniq | MolScribe | DECIMER | OPSIN(names) |
|-------|-----------|-----------|---------|--------------|
| intechopen.108949 (bis-heterocycles) | 4 | 0 | 0 | n/a |
| antibiotics10081002 (pyrazoline-benzimidazoles, review) | 57 | 1 | 3 (+2 new) | 0 |

## smiles-F1 effect
- antibiotics10081002 alone: 0.0052 (MolScribe) -> 0.0260 (+DECIMER ensemble).
- benzimidazole overall: /7 Macro +0.0004, smiles 0.138->0.141; /allOA smiles 0.108->0.110.

## Honest conclusion
- DECIMER is a useful COMPLEMENTARY engine: ensemble (MolScribe u DECIMER) is strictly >= either alone, captures structures MolScribe misses. But gains are marginal in absolute terms.
- The ceiling is structural complexity, now confirmed across TWO independent OCSR architectures: both fail on intechopen's fused bis-heterocycles; both capture only ~3-5% of antibiotics10081002's 57 decorated structures. Not a single-model artifact.
- OPSIN (IUPAC name parsing) does NOT rescue review-style papers: antibiotics10081002 names are templates with '(aryl)' placeholders, not explicit per-compound names, so claude-opus extracted only 6 and OPSIN hit 0. (Contrast oxazolidinone: explicit per-compound names -> OPSIN 17/17 exact.)

## Practical takeaway
Smiles strategy should be matched to paper type, not forced through one engine:
- explicit systematic names in experimental section -> IUPAC->OPSIN (best, exact).
- trivial drug names -> name->PubChem.
- figure-only structures -> OCSR ensemble (MolScribe + DECIMER), union_clean.
The remaining smiles=0 papers (intechopen, s41598 salts) are at the OCSR frontier; meaningful lift would need a fine-tuned/newer OCSR (e.g. MolNexTR) or curated structures.
Scripts: seg_stage.py (segmentation), decimer_stage.py (DECIMER inference). Crops on 3080 /home/ubuntu/scinex/chemx/crops/.

## Gemini-3.1-Pro as vision OCSR (multimodal LLM)
call_vision('gemini-pro', ...) on rendered pages, prompt -> JSON [{label,smiles}], expand Markush. RDKit canonical + complete-core filter.

### Latency finding
- per-CROP, single-SMILES prompt: 35-117 s/call (model over-reasons on isolated crops) -> impractical.
- batch full-PAGE, JSON prompt: ~10-12 s per 3 pages -> fast & practical. Use full pages, not crops.

### Gold overlap (unique correct structures)
| paper | gold | MolScribe | DECIMER | Gemini-3.1 | union(all 3) |
|-------|------|-----------|---------|------------|--------------|
| intechopen.108949 | 4 | 0 | 0 | 0 | 0 |
| antibiotics10081002 | 57 | 1 | 3 | 2 (2 disjoint from DECIMER) | ~5-6 |

antibiotics10081002 smiles-F1: 0.0052 (MolScribe) -> 0.0260 (+DECIMER) -> 0.0364 (+Gemini).

### Honest verdict on Gemini-vision
- Complementary, not a breakthrough. Adds gold structures the OCSR engines miss, but absolute coverage stays ~10% on hard review papers; 0/4 on intechopen bis-heterocycles (all 3 engines fail).
- Low precision: extracted 207 valid structures on antibiotics to land 2 gold matches -> the complete-core filter is mandatory or it floods the pool with FP.
- Ceiling now confirmed across THREE independent engines (specialized OCSR x2 + frontier VLM). These fused/decorated structure classes are the real frontier; not a single-model artifact.
- Best practice: ensemble pool = MolScribe u DECIMER u Gemini(core-filtered), union_clean. Marginal but strictly >=.

Scripts: gem_pages.py / gem_pages2.py (batch full-page vision OCSR), gem_vision.py (per-crop, deprecated: too slow).

## CORRECTION: Claude-opus vision is the dominant OCSR engine (earlier 3-engine 'ceiling' was wrong)
The earlier conclusion -- OCSR ceiling confirmed across MolScribe/DECIMER/Gemini -- tested three WEAK
engines. Tested claude-opus as a vision-OCSR engine (same full-page batch JSON protocol):

| engine | antibiotics10081002 gold (57) | intechopen.108949 gold (4) |
|--------|-------------------------------|----------------------------|
| MolScribe | 1 | 0 |
| DECIMER   | 3 | 0 |
| Gemini-3.1| 2 | 0 |
| **Claude-opus** | **26** | **2** |

- Claude alone (26) ~= full union (28). Gemini+MolScribe+DECIMER add only ~2 over Claude.
- antibiotics smiles-F1: 0.0364 (MolScribe+DECIMER+Gemini) -> **0.0935** (+Claude), 2.6x.
- intechopen: Claude got 2/4 bis-heterocycles that NO specialized OCSR or Gemini could read. The
  'ceiling' was a weak-model artifact, not a real frontier. (Claude got the benzene-fused variants,
  missed the aza-pyridine-fused ones -> looks like genuine reading, not pure knowledge recall.)
- Caveat: benchmark papers are published; some knowledge-augmentation can't be ruled out. For a novel
  paper pure-vision skill matters more -- but for ChemX scoring this is a real, large win.

### Revised VLM role
Claude-opus = PRIMARY vision/figure engine (not Gemini). MolScribe+DECIMER kept as free local base
(add ~2 disjoint, zero cost). Gemini demoted (2/57, paid, worse than free locals+Claude) -> drop from
default, keep only as an optional extra. Consensus beyond Claude is marginal (28 vs 26): not worth
default cost. Scripts: claude_vision_test.py (full-page batch). Claude-vision latency ~27-90s/3pg
(slower than Gemini 12s) but the accuracy delta dwarfs the latency cost.

### Is Gemini needed for consensus? NO -- it hurts.
antibiotics10081002: Claude+MolScribe+DECIMER gold=28; +Gemini gold=28 (marginal 0 -- Gemini's 2 hits
are a subset of Claude's 26). smiles-F1: Claude+Mol+DEC = 0.1610; +Gemini = 0.1195 (Gemini's ~205 false
positives dilute precision). Gemini DROPPED entirely, not demoted.

**Final OCSR ensemble = Claude-opus vision (PRIMARY) + MolScribe + DECIMER (free local base).** No Gemini.
Orchestrator end-to-end on antibiotics: smiles-F1 0.0052 (MolScribe baseline) -> 0.1506 (29x).
