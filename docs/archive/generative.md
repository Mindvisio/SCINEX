# scinex — Generative module (FUTURE; NOT on the ChemPaperBench critical path)

Boundaried future module, orthogonal to ChemPaperBench (paper-QA). Layering locked now so it does not
bleed into core or the benchmark. Build only AFTER core (index/+qa/) + the chem-QA module land. PARKED.

## Idea — three-layer drug-discovery stack
scinex (knowledge) -> LOGOS (generator) -> classical oracle (score/rank). The MADD generate->score->rank
loop, but with a strong shared-grammar generative core.
- scinex (data/knowledge): retrieval (9 sources incl. ChEMBL/BindingDB) + reasoning graph (mode C) assemble
  a target dossier — known actives, prior art, binding data — as the generation context.
- LOGOS (generator): SEPARATE API service. "Language of Generative Objects in Science" (arXiv 2606.16905;
  RUC GSAI + Alibaba; weights LOGOS-Hub/LOGOS-{1,3,8}B + 8B-SFT; CC-BY-4.0). One autoregressive model over a
  unified "scientific grammar" (discrete tokens for proteins/antibodies/molecules/reactions/materials +
  spatial contacts; no explicit 3D). Tasks: pocket->ligand design, retrosynthesis, material gen, protein
  editing, antibody CDR. NOT chat/vision — eats tokenized domain-native input, not NL.
- classical oracle (validate/rank): RDKit (validity/alerts/QED/SA) -> docking (AutoDock Vina) -> ADMET ->
  QSAR/screening. Ranks LOGOS candidates.

## Integration contract (the real work, not "just call a model")
1. Grammar codec: per-task encode/decode between scinex objects and LOGOS grammar tokens (pocket-tokens ->
   ligand-tokens; product-SMILES -> reactant-SMILES). Build the token prompt; parse output back to SMILES/seq.
2. Two tiers: LOGOS = broad generalist proposer; on top -> LoRA/SFT on our data + NARROW critics
   (target-specific affinity/QSAR, our ADMET) for sharp scoring where the generic output is weak.
   Generalist proposes, specialists reject.
3. Service: standalone FastAPI inference (token-in/token-out) on a GPU node; 1B/3B on immers now, 8B later/
   quantized. scinex calls it as a tool via the lib/ gateway pattern. NOT in core.

## Status: PARKED — tracking only. No code until core + chem-QA module are done.
