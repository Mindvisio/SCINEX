# ChemX PDF Tools

Набор скриптов для получения open-access PDF по ChemX/Hugging Face датасетам.

## Установка

```bash
pip install -r requirements.txt
```

## 1. Сделать manifest DOI по домену

```bash
python 01_make_chemx_oa_manifests.py --domain benzimidazole
```

По всем доменам:

```bash
python 01_make_chemx_oa_manifests.py --domain all
```

Результат:

```text
manifests/benzimidazole_open_access_manifest.csv
manifests/_summary_open_access.csv
```

## 2. Скачать PDF через Unpaywall

```bash
python 02_download_chemx_pdfs.py \
  --domain benzimidazole \
  --email your_email@example.com \
  --out data/pdfs
```

По всем доменам:

```bash
python 02_download_chemx_pdfs.py \
  --domain all \
  --email your_email@example.com \
  --out data/pdfs
```

Результат:

```text
data/pdfs/pdf_benzimidazole/<pdf_id>.pdf
manifests/benzimidazole_download_report.csv
```

## 3. Проверить скачанные PDF

```bash
python 03_check_downloaded_pdfs.py --domain benzimidazole
python 03_check_downloaded_pdfs.py --domain all
```

## 4. Список того, что надо добить вручную

```bash
python 04_make_manual_download_list.py --domain benzimidazole
python 04_make_manual_download_list.py --domain all
```

## 5. Сводка

```bash
python 05_print_domain_summary.py
```

## Поддерживаемые short names

```text
eyedrops
benzimidazole
oxazolidinone
nanozymes
synergy
nanomag
cocrystals
complexes
cytotox
seltox
all
```

## Важно

- Скрипты не обходят paywall.
- Автоматически скачиваются только легальные OA PDF, найденные через Unpaywall.
- Если DOI не скачался автоматически, смотри `*_manual_download_list.csv`.
- Для ChemX evaluator важно, чтобы в `pred.csv` колонка `pdf` совпадала со значением ChemX/HF `pdf`.
