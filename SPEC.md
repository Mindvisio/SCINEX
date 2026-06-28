# scinex — SPEC (contract, v0.4)

Lean by design. Pins load-bearing contracts, not a roadmap.
v0.4: core is DOMAIN-AGNOSTIC and supports THREE modes — (A) extraction pipeline, (B) paper QA,
(C) reasoning graph over extracted records. Domains (chemistry, longevity, ...) are pluggable PRESETS.
Concrete deliverables are domain MODULES (core + preset + eval); per-module specs live in docs/ (e.g. docs/chemistry.md).

## 0. Layering (build order) — DO NOT MIX
1. CORE    — domain-agnostic capabilities + contracts. Build/solidify first; keep domain-free.
2. PRESETS — domains/: a domain plugs in via a small declared interface; no core edits.
3. MODULES — docs/<domain>.md: apply core+preset to a concrete goal/benchmark.
Boundary: CORE knows nothing about any domain. A PRESET declares {focus types, entity kinds, id schemes,
validators, extract hint, tools, vocab}. A MODULE wires data + eval + (optional) domain harness.
Lead module: chemistry -> ChemPaperBench (docs/chemistry.md). FUTURE module:
 generative drug-discovery scinex->LOGOS->classical-oracle, PARKED (docs/generative.md).

## 1. Purpose
Domain-agnostic literature engine for Datacon 2026: retrieve -> parse -> (index) -> {extract | answer}
-> reason (graph) -> summarize / export / analytics.

## 2. Core capabilities (domain-agnostic)
- retrieval/ : search across 9 sources (done). Dedup DOI+title. Also fetch full text/PDF by DOI.
- ocr/       : PDF -> text + tables + figures. Mathpix (text/LaTeX/tables) + figure extraction.
               ocr/ocsr.py = chemical-structure image -> SMILES (DECIMER); used by the chem preset only.
- index/     : chunk + embed (API embeddings, not self-hosted) + retrieve + rerank over a paper corpus.
               RAG substrate for mode B. Corpus is small (per-module), so API embeddings suffice.
- extraction/: (mode A) papers -> typed ExtractedRecord (extractor -> reconciler -> validator).
- qa/        : (mode B) question -> index.retrieve(text+figures) -> vision-LLM answer. Domain-agnostic.
- graph/     : (mode C) reasoning graph over ExtractedRecord (nodes/edges/typed claims); merges prior
               knowledge (ChEMBL/Rhea/ontologies) + extracted entities; powers analytics + GraphRAG.
               Reuses proof-graph-as-DAG machinery from Proof Engine.
- summarize/ : per-paper summaries + corpus review. model = SUMMARIZE_MODEL.
- export/    : records / review -> TeX / md / docx / pdf / csv / json.
- lib/       : LLM gateway (6 channels; vision via claude-opus / gpt-5.5-pro).

DOMAIN LAYER (domains/): presets specialize extraction focus + prompts + per-kind validators/tools + vocab.
Core never hardcodes a domain; set DEFAULT_DOMAIN or pass one.

## 3. ExtractedRecord (substrate) — extraction/schema.py
Envelope fixed; per-type payload in `normalized`. Fields: record_id, paper, entity_type, value, normalized,
quantity, unit, span (verbatim quote + recomputed char offsets), extractor, confidence, validation,
validation_detail, extracted_at. Provenance: span.quote MUST be a verbatim substring; ungrounded records dropped.
EntityType = 5 STRUCTURAL kinds (domain-agnostic): ENTITY, RELATION, CLAIM, METHOD, MEASUREMENT.
Domain kinds (molecule/reaction/gene/organism/...) live in entity.normalized["type"] (string), NOT the enum.
identifiers = open map {scheme: value} (SMILES/InChI/InChIKey/CAS/PubChem/ChEMBL/PDB/UniProt/HGNC/...),
schemes registered per preset. key() dispatches per type (entity id prioritizes inchikey/inchi/smiles).
These 5 types ARE graph-shaped (see mode C): ENTITY=node, RELATION=edge, CLAIM=polar assertion.

## 4. Extraction pipeline (mode A, multi-agent) — extraction/
extractor (bulk, deepseek-v4-pro) -> reconciler -> validator.
- extractor(text, paper_ref, domain=None): domain hint + entity kinds injected; validation=unverified.
- reconciler: merge identical via key() (raises confidence); escalate only low-confidence/conflicts to
  RECONCILE_MODEL (claude-opus, max).
- validator(rec, domain): generic checks + preset validators (chemistry -> RDKit canonical SMILES + PubChem).
Tools (RDKit/OCSR/OPSIN) run DETERMINISTICALLY in-pipeline (post-process), NOT as LLM-decided function calls;
expose a tool to the agent only where it genuinely chooses, and only if ablation shows lift.

## 5. QA pipeline (mode B) — qa/
question -> index.retrieve(text + figures) -> vision-LLM answer (claude-opus / gpt-5.5-pro). Domain-agnostic.
Corpus built from retrieval/ (fetch PDFs by DOI) + ocr/ (parse) + index/ (embed). Eval is per-module.

## 6. Reasoning graph (mode C) — graph/
A layer OVER ExtractedRecord, NOT a separate pipeline. The 5 structural types are a graph: ENTITY=node,
RELATION=typed edge, CLAIM=polar assertion (subj-pred-obj + polarity + retracted), METHOD/MEASUREMENT=
attributes. One graph holds BOTH (a) prior knowledge imported from DBs/ontologies (ChEMBL, Rhea/KEGG,
ChEBI, ...) and (b) extracted records (mode A). Reasoning over the union: ground extracted entities to
known IDs; detect novelty (edges absent in (a)); detect contradictions (opposing CLAIM polarities +
retraction flags); propose+test hypotheses (suggest edges, verify) — same proof-graph-as-DAG machinery
reused from Proof Engine.
Uses:
- ANALYTICS (the 9) = queries over this graph.
- GraphRAG = subgraph/path retrieval over the knowledge graph; a TARGETED booster for multi-step /
  cross-paper questions (mode B's weak spot — flat chunk-RAG degrades on L2/L3).
Boundary vs index/ (mode B): index/ = vector RAG over text/figure CHUNKS (recall under a question);
graph/ = structured reasoning over typed RECORDS (relations, contradictions, multi-hop). Complementary.
Build order: mode B first (bulk L1/L2); graph/ second (analytics + GraphRAG on L3/cross-paper). Records
are already graph-shaped, so graph/ slots in without reshaping extraction or index/.

## 7. Eval — eval/
Mode A: ~20-paper gold; per-type P/R/F1 + macro-F1; null baseline. coverage_probe.py = dedup union vs AnswerThis.
Mode B: per-module benchmark harness (chem -> G-Eval vs ChemPaperBench baselines; see docs/chemistry.md).

## 8. Analytics (the 9) — analysis/   [queries over the mode-C graph, §6]
1 trends | 2 combinations (co-occurrence) | 3 intersections (set algebra) | 4 contradictions (claim-polarity
+ retraction: OpenAlex is_retracted / Crossref notices) | 5 gap matrix (bipartite intervention x organism) |
6 PRISMA | 7 citation graph (OpenAlex referenced_works/cited_by) | 8 semantic map (SPECTER2 via S2 -> UMAP) |
9 other. Views over records + metadata + enrich/.

## 9. Enrichment (cheat layer) — enrich/
SPECTER2 via Semantic Scholar; OpenAlex topics + citations. No self-hosted embeddings.

## 10. Non-goals / stack
No self-hosted embeddings, no pgvector, no Kubernetes. FastAPI core; React+Vite + Plotly/visx frontend.
Postgres JSONB store (store/). Python 3.10/3.11. Per-domain module specs in docs/.
