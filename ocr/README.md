# ocr / OCSR — chemical structures -> SMILES

Two OCR concerns:
- **mathpix.py** : PDF text/formula/tables -> Markdown+LaTeX (existing). NOT for chemical structures.
- **ocsr.py**    : chemical STRUCTURE images -> SMILES (+ reaction schemes). The Datacon core.

## Why OCSR is its own subsystem
Chemical data in papers is mostly drawn structures (figures), not text. Mathpix can't read them.
So molecule/reaction extraction = detect figures -> OCSR model -> SMILES -> RDKit canonical (domains.chemistry).

## Backends (named at the Datacon conf)
- **OpenChemIE** (PRIMARY, integrator): molecules + reactions + text from chemistry PDFs (wraps
  MolScribe + RxnScribe). One package covers most of the task.
- MolScribe: molecule image -> SMILES (deep). RxnScribe: reaction scheme -> structured reaction.
- DECIMER: molecule image -> SMILES (deep, TF). OSRA / MolVec: classical CPU fallbacks.

## Where it runs
Deep models need a GPU. immers (RTX 3080, ~8.4 GB free VRAM) is the prod node, but its disk is tight
(~15 GB free) — free space before installing the full stack there. For dev/correctness, run on a
sci-node CPU venv (torch present, ~44 GB disk). Text->SMILES complements OCSR: OPSIN (IUPAC name ->
structure) + PubChem/ChEMBL (trivial names) — see domains.chemistry tools.

## Eval
Score canonical-SMILES / InChIKey match against the Datacon hand-annotated benchmark (replaces the
self-authored gold set; wire into eval/).

## TODO
Install OpenChemIE (+ MolScribe) in a venv; wire ocsr.image_to_smiles / extract_reactions per backend;
add a figure-detector (or rely on OpenChemIE's); GPU runner that dispatches to immers.
