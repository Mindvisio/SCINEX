# scinex — Chemistry module (preset + ChemPaperBench)

MODULE = core (domain-agnostic) + chemistry PRESET + the ChemPaperBench benchmark attempt.
Keeps chem/benchmark specifics OUT of SPEC.md.

## 1. Chemistry preset — domains/chemistry.py
- entity kinds: molecule, reaction, target, material
- id schemes (open map): SMILES, InChI, InChIKey, CAS, PubChem CID, ChEMBL, ChEBI, UniChem, ...
- validators: molecule -> RDKit canonical SMILES + InChIKey (core never imports RDKit)
- preset tools:
  - RDKit          : canonicalize, InChIKey, alerts (PAINS/Brenk via FilterCatalog), QED, SA
  - PubChem PUG-REST, ChEMBL : name/identifier -> structure
  - OPSIN          : IUPAC name -> structure (text -> SMILES)
  - OCSR (ocr/ocsr.py) : structure IMAGE -> SMILES. Backend = DECIMER (installed, .venv-decimer, py3.10).
                     MolScribe/OpenChemIE need py3.8 (onmt->torchtext) -> deferred to a docker iff needed.
  - reactions w/o Reaxys (open DBs): Open Reaction Database, USPTO/Lowe, Rhea/KEGG

## 2. ChemPaperBench — the benchmark
Dataset: huggingface.co/datasets/ITMO-NSS/ChemPaperBench. Harness: github.com/ITMO-NSS-team/chempaperbench.
Local: benchmarks/_cpb/chempaperbench.csv (376 Q) ; benchmarks/chempaperbench-code/ (harness).
- 376 expert Q over ~63 papers, 8-9 chem domains; multimodal: 68% reference a figure, 18% a table, 90% text.
- levels: L1 retrieval (227) / L2 synthesis+multimodal+calc (93) / L3 multi-step cross-paper (56).

### Contract (LOCKED — read from harness)
Input = QUESTION ONLY. System retrieves text+figures from a corpus of the papers; a vision-LLM answers.
The csv txt/img/table_context is GOLD, NOT given at inference.
Metric = DeepEval GEval(name="Correctness"); 4 steps (numbers -> facts -> filler -> "no answer = very low");
judge = openai/gpt-4o-2024-08-06 via OpenRouter; score [0,1]; failures = -1 (excluded from mean).
Replicate 1:1 or numbers are not comparable.

### Baseline bar (G-Eval Correctness, excl -1)
MAS-RAG 0.650  (by level: L1 0.70 / L2 0.62 / L3 0.50)   <- TARGET to beat
Gemini-2.5 0.46 . GPT-5 0.45 . ChemToolAgent 0.42 . DeepSeek-3.1 0.42 . Llama-4 0.40
Headroom is L2/L3. Our edge: stronger models (Opus 4.8 / GPT-5.5-pro / DeepSeek-V4 vs their
GPT-5 / Gemini-2.5 / DeepSeek-3.1 / Llama-4) + retrieval/rerank quality + figure handling.

### Plan
M0  G-Eval scorer 1:1 (DeepEval GEval + gpt-4o-2024-08-06 judge via OpenRouter). VALIDATE by re-scoring
    their provided answers (_cpb/mas_rag_results.csv) -> must reproduce ~0.65. [.venv-bench, deepeval 4.0.6 ready]
M1  our models STANDALONE (question-only, their sys prompt) on 376 Q -> G-Eval. NO corpus. Our floor vs
    their standalone (~0.45).
M2  multimodal RAG (NEEDS corpus): fetch 63 PDFs by DOI -> ocr/ parse (text+figures) -> index/ (API embed
    + rerank) -> qa/ vision-LLM answer -> G-Eval. Target >0.65, lift L2/L3.

### Corpus (M2 blocker)
63 PDFs by DOI; not in repo (copyright). Sourcing TBD: Sci-Hub MCP (connected) / institutional / open-only.
M0 + M1 need no corpus.

### Status
done: dataset+harness cloned; contract/metric/bar extracted; judge access (OpenRouter gpt-4o); DECIMER OCSR; deepeval ready.
next: M0 scorer + validation -> M1 standalone runs -> (corpus) -> M2 RAG.
