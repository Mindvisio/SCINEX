# SCINEX — установка и воспроизведение

Два уровня. Для базового пути (hosted-LLM) достаточно **Core**. Локальные OCSR-движки — опциональны.

## 1. Core (минимум)

```bash
uv venv --python 3.11 .venv && uv pip install -p .venv/bin/python -r requirements.txt
# или: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env        # минимум: ANTHROPIC_API_KEY, DEEPSEEK_API_KEY
```
Системные пакеты (tabula/OPSIN/camelot/pdftotext): `default-jre-headless ghostscript poppler-utils`.

`requirements.txt` — это **только core** (.venv-lite). Хватает для основного конвейера: vision-OCSR (Claude), текстовый оркестратор (DeepSeek), OPSIN (IUPAC→SMILES), PubChem (name→structure), Mathpix/Mistral OCR (по ключам). Локальные модели не нужны.

## 2. Опциональные локальные OCSR-движки

VRAM ~8 ГБ → одна модель за раз. Каждый движок — в **отдельном** venv (фреймворки взаимно несовместимы). Рекомендуется `uv`.

**MolScribe + OpenChemIE** (torch 1.13 / cu117):
```bash
uv venv --python 3.10 .venv-chem
uv pip install -p .venv-chem/bin/python "torch==1.13.1+cu117" "torchvision==0.14.1+cu117" --index-url https://download.pytorch.org/whl/cu117
git clone https://github.com/CrystalEye42/OpenChemIE.git
uv pip install -p .venv-chem/bin/python -e ./OpenChemIE
# при конфликтах: pin numpy<2 и transformers==4.39.3
```
**DECIMER** (TensorFlow):
```bash
uv venv --python 3.10 .venv-decimer
uv pip install -p .venv-decimer/bin/python decimer
```
**DECIMER-segmentation**:
```bash
uv venv --python 3.10 .venv-decimerseg
uv pip install -p .venv-decimerseg/bin/python decimer-segmentation   # pin numpy<2
```
**marker-pdf** (опц., парсинг документов; ~1.4 ГБ surya на первом запуске):
```bash
uv venv --python 3.11 .venv-marker
uv pip install -p .venv-marker/bin/python --index-url https://download.pytorch.org/whl/cu128 --reinstall-package torch --reinstall-package torchvision marker-pdf
```
**ChemDataExtractor2** (опц.):
```bash
uv venv --python 3.10 .venv-cde
uv pip install -p .venv-cde/bin/python ChemDataExtractor2
```
Веса (MolScribe ckpt, DECIMER/surya/OpenChemIE) тянутся при первом запуске (gitignored).

## 3. Проброс движков в core

Core вызывает локальные venv'ы по путям из окружения (см. `.env.example`, секция «локальные пути»):
```
MOLSCRIBE_PYTHON=/abs/.venv-chem/bin/python
OPENCHEMIE_PYTHON=/abs/.venv-chem/bin/python
DECIMER_PYTHON=/abs/.venv-decimer/bin/python
DECIMER_SEG_PYTHON=/abs/.venv-decimerseg/bin/python
GROBID_URL=http://localhost:8070   # опц.
```
Детальные заметки по железу/версиям/подводным камням: `docs/SETUP_3080.md`, `docs/TOOLS_3080.md`.

## 4. Воспроизведение метрики

Пути к gold/baseline — в шапке каждого скрипта (gold в репо: `chemx/data/gold/`).
```bash
# бензимидазолы (9 статей): Macro-F1 0.461 vs baseline 0.217
python chemx/scripts/build_benz_pred.py
python hw_chemdb/metric_local.py --dataset benzimidazole --source single_agent --pred chemx/results/benz_pred_final.csv
# оксазолидиноны (end-to-end): Macro-F1 0.828 vs baseline 0.491
python chemx/scripts/oxa_score.py
```

## 5. Веб-демо

Читает готовый `chemx/results/benz_pred_final.csv`, ключи не нужны:
```bash
cd web && python -m uvicorn app:app --host 127.0.0.1 --port 8088   # http://127.0.0.1:8088
```
