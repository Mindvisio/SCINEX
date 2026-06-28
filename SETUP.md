# SCINEX — установка и воспроизведение

Два уровня. Базовый путь (hosted-LLM) — только **Core**. Локальные OCSR-движки опциональны и ставятся каждый в свой venv (фреймворки взаимно несовместимы по torch/TF/numpy).

## 1. Core (hosted-LLM)

```bash
uv venv --python 3.11 .venv-lite
uv pip install -p .venv-lite/bin/python -r requirements.txt
# или: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env        # минимум: ANTHROPIC_API_KEY, DEEPSEEK_API_KEY
```
Системные пакеты (OPSIN/tabula/camelot/pdftotext):
```bash
sudo apt install -y default-jre-headless ghostscript poppler-utils libpoppler-cpp-dev pkg-config python3-dev build-essential
```
`requirements.txt` — только core. Хватает для основного конвейера: vision-OCSR (Claude), оркестратор (DeepSeek), OPSIN (IUPAC→SMILES), PubChem (name→structure), Mathpix/Mistral OCR по ключам. Локальные модели не нужны.

## 2. Веб-демо (отдельный лёгкий набор)

`requirements.txt` НЕ тянет FastAPI/uvicorn. Для бэкенда/демо:
```bash
uv pip install -p .venv-lite/bin/python -r requirements-web.txt
cd web && python -m uvicorn app:app --host 127.0.0.1 --port 8088   # http://127.0.0.1:8088
```
Читает готовый `chemx/results/benz_pred_final.csv`, ключи не нужны.

## 3. Опциональные локальные OCSR-движки

VRAM ~8 ГБ → одна модель за раз. Веса (MolScribe ckpt, DECIMER/OpenChemIE) тянутся при первом запуске (gitignored).

### MolScribe + OpenChemIE — `.venv-chem` (torch 1.13.1 / cu117)
OpenChemIE фиксирует старый стек (torch<2, numpy<2, transformers 4.39.3) — строго отдельный venv:
```bash
uv venv --python 3.10 .venv-chem
uv pip install -p .venv-chem/bin/python -U pip setuptools wheel
uv pip install -p .venv-chem/bin/python \
  --extra-index-url https://download.pytorch.org/whl/cu117 \
  torch==1.13.1+cu117 torchvision==0.14.1+cu117
uv pip install -p .venv-chem/bin/python \
  "numpy<2" "transformers==4.39.3" "huggingface-hub<1" \
  "opencv-python==4.5.5.64" "Pillow==9.5.0" rdkit
mkdir -p third_party
[ -d third_party/OpenChemIE ] || git clone https://github.com/CrystalEye42/OpenChemIE.git third_party/OpenChemIE
uv pip install -p .venv-chem/bin/python -e third_party/OpenChemIE
```

### DECIMER — `.venv-decimer` (TensorFlow 2.20)
```bash
uv venv --python 3.10 .venv-decimer
uv pip install -p .venv-decimer/bin/python -U pip setuptools wheel
uv pip install -p .venv-decimer/bin/python "tensorflow[and-cuda]==2.20.*" "decimer==2.8.0"
```

### DECIMER-segmentation — `.venv-decimerseg` (TensorFlow 2.14; НЕ смешивать с DECIMER)
```bash
uv venv --python 3.10 .venv-decimerseg
uv pip install -p .venv-decimerseg/bin/python -U pip setuptools wheel
uv pip install -p .venv-decimerseg/bin/python \
  "numpy<2" "tensorflow==2.14.*" "decimer-segmentation==1.5.0" opencv-python-headless PyMuPDF
```

(опц.) marker-pdf — `.venv-marker`; ChemDataExtractor2 — `.venv-cde`: см. `docs/SETUP_3080.md`.

## 4. Проброс движков в core

Core шеллит локальные venv'ы по путям из `.env`:
```
MOLSCRIBE_PYTHON=/abs/path/.venv-chem/bin/python
OPENCHEMIE_PYTHON=/abs/path/.venv-chem/bin/python
DECIMER_PYTHON=/abs/path/.venv-decimer/bin/python
DECIMER_SEG_PYTHON=/abs/path/.venv-decimerseg/bin/python
GROBID_URL=http://localhost:8070   # опц.
```
Если не задано — `ocr/ocsr.py` пробует repo-relative `./.venv-chem` / `./.venv-decimer`, иначе текущий python.

**Ансамбль OCSR по умолчанию** = `vision + DECIMER` (`images_to_smiles(engines=...)`). MolScribe/OpenChemIE — опциональные GPU-движки, включаются явно: `engines=("vision","molscribe","decimer")`.

## 5. Воспроизведение метрики

Пути к gold/baseline — в шапке скриптов (gold в репо: `chemx/data/gold/`).
```bash
# бензимидазолы (9 статей): Macro-F1 0.461 vs baseline 0.217
python chemx/scripts/build_benz_pred.py
python hw_chemdb/metric_local.py --dataset benzimidazole --source single_agent --pred chemx/results/benz_pred_final.csv
# оксазолидиноны (end-to-end): Macro-F1 0.828 vs baseline 0.491
python chemx/scripts/oxa_score.py
```

## 6. Проверка окружений

```bash
nvidia-smi
.venv-chem/bin/python -c "import torch; from molscribe import MolScribe; from openchemie import OpenChemIE; print('chem ok', torch.__version__, torch.cuda.is_available())"
.venv-decimer/bin/python -c "import tensorflow as tf; from DECIMER import predict_SMILES; print('decimer ok', tf.__version__, tf.config.list_physical_devices('GPU'))"
.venv-decimerseg/bin/python -c "import tensorflow as tf; from decimer_segmentation import segment_chemical_structures; print('seg ok', tf.__version__)"
```
