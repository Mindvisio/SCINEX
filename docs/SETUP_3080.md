# scinex — GPU tool stack on RTX 3080 (<cloud-provider> / <gpu-node>)

Host: `<user>@<gpu-node>` (SSH alias `immers`). RTX 3080 10GB, driver 570.86 (**CUDA 12.8 ceiling**, not 13), Ubuntu 24.04, Py3.12 system, 16c/31G. Repo: `<repo-path>`.
Isolation: one `uv`-managed venv per tool (own Python, own cache), **no system pip**, prod untouched (voice-trainer + TotalSpineSeg segmentator verified intact). uv at `~/.local/bin/uv`.

## Environments (all built + verified)

| venv | Py | stack | GPU | verified |
|---|---|---|---|---|
| .venv-chem | 3.10 | torch 1.13.1+cu117 · OpenChemIE 0.1.0 (MolScribe 1.1.1 + RxnScribe 1.0) · transformers 4.39.3 · numpy 1.26.4 | YES (cuda True) | MolScribe exact recovery; PDF end-to-end 52 mols / 8pp / 35s |
| .venv-decimer | 3.10 | DECIMER 2.8 · TF 2.20.0 | YES (GPU:0) | import + model dl |
| .venv-decimerseg | 3.10 | decimer-segmentation 1.5 · TF 2.14.0 · numpy<2 | no (CPU) | import |
| .venv-marker | 3.11 | marker-pdf 1.10.2 · surya 0.17 · torch 2.11.0+cu128 | YES (cuda True) | import |
| .venv-cde | 3.10 | ChemDataExtractor 2.4.0 (+models) | CPU | import + benzene NER |
| .venv-lite | 3.11 | anthropic/openai/google-genai/httpx/pydantic · rdkit · pymupdf · py2opsin · tabula · camelot · numpy 2.4.6 | CPU | all imports + OPSIN/tabula/camelot |

## apt added (additive only, prod-safe)
`libpoppler-cpp-dev pkg-config` (pdftotext build) · `poppler-utils` (pdf2image CLI) · `default-jre-headless` (tabula + OPSIN) · `ghostscript` (camelot).

## Build recipe (each venv)
```
export PATH=\$HOME/.local/bin:\$PATH; cd <repo-path>
uv venv --python <ver> .venv-X
uv pip install -p .venv-X/bin/python <pkgs>
```
chem: torch from `--index-url https://download.pytorch.org/whl/cu117` then `uv pip install -e ./OpenChemIE` (clone CrystalEye42/OpenChemIE), then pin `numpy<2` + `transformers==4.39.3`.
marker torch GPU: `uv pip install -p .venv-marker/bin/python --index-url https://download.pytorch.org/whl/cu128 --reinstall-package torch --reinstall-package torchvision torch torchvision`.

## Known issues / fixes
- **numpy 2.x breaks old binaries** (cv2 / torch1.13 / TF<=2.15: `_ARRAY_API not found`, `VisibleDeprecationWarning`) -> pin `numpy<2` (chem, decimerseg).
- **transformers too new** disables torch<2.4 -> pin `transformers==4.39.3` (chem).
- **torch CUDA mismatch**: pip default = +cu130 (CUDA13) -> cuda False on drv570. Use cu128 index AND `--reinstall-package torch` (plain `==ver` is wrongly satisfied by the +cu130 local tag).
- **layoutparser PubLayNet detector** (`extract_*_in_pdf`) downloads from Dropbox -> returns HTML (`invalid load key '<'`). Workaround: pdf2image render pages + `extract_molecules_from_figures(imgs)` (MolDetect+MolScribe, HF-hosted). TODO: fetch effdet ckpt manually for full _in_pdf path.
- **full-page OCSR noisy**: MolDetect on whole pages catches non-structures -> MolScribe hallucinates ([Bi]xN, gibberish). Fix: crop isolation (figure detector / Mathpix crops) + RDKit validity + detection-confidence filter.
