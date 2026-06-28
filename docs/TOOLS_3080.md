# Tools & deps for 3080 migration

3080 = 176.99.131.77 (immers.cloud), ~8.4 GB VRAM -> run ONE model at a time.
Three mutually-incompatible framework envs — keep in SEPARATE venvs (as on sci-node):

## A. torch 1.13.1 (cu117) — structure/reaction recognition
- MolScribe 1.1.1 — pip install MolScribe==1.1.1 ; src github.com/thomas0809/MolScribe ; ckpt swin_base_char_aux_1m.pth
- RxnScribe 1.0 — github.com/thomas0809/RxnScribe
- OpenChemIE 0.1.0 — git clone github.com/CrystalEye42/OpenChemIE @ d9b50bb ; pip install -e . (pulls MolScribe+RxnScribe, transformers 4.39.3, onnxruntime, timm 0.4.12, rdkit-pypi 2022.9.5, torchvision 0.14.1)

## B. TensorFlow — DECIMER OCSR + segmentation
- decimer 2.8.0 — pip install decimer (TF 2.20) ; Kohulan/DECIMER-Image_Transformer ; downloads model on first run
- decimer-segmentation 1.5.0 — pip install decimer-segmentation (TF 2.15)

## C. torch 2.12 — document parsing (official baseline preprocessing)
- marker-pdf 1.10.2 — pip install marker-pdf (pulls surya-ocr 0.17.1, transformers 4.57.6) ; downloads ~1.4 GB surya models on first run

## CPU/API — STAY on sci-node, do NOT move to 3080
- Camelot 2.0.0 + Tabula 2.10.0 (.venv-tables) — text-table extraction ; needs ghostscript + JRE
- Mathpix / Mistral OCR — cloud API (keys in /root/.api_keys)
- LLM gateway lib/llm_clients — deepseek/gemini/claude/novita

## Phase-2 candidates (NOT yet cloned) — for smiles lever (SAR/Markush)
- MolNexTR — github.com/CYF2000127/MolNexTR (SOTA printed OCSR)
- MolParser — Markush / E-SMILES / wild structures
- RxnIM — reaction-scheme parsing

## Checkpoints / caches (gitignored, re-download on 3080)
MolScribe ckpt ; DECIMER models (HF) ; surya models (HF ~1.4 GB) ; OpenChemIE weights.

## Repo workers ready to ship to 3080
ocr/ocsr.py (MolScribe+DECIMER+vision consensus, RDKit/InChIKey arbiter, TTA) ; ocr/molscribe_worker.py ; ocr/decimer_worker.py ; ocr/decimer_seg_worker.py ; ocr/openchemie_worker.py ; ocr/dispatch.py (router).
