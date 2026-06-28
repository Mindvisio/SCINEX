# Карта промптов scinex

Все LLM-промпты — inline-строки в коде (видны в исходниках). Маршрутизация (OPSIN/PubChem/OCSR, выбор OCR-движка) — детерминированная, без LLM. Центральный оркестратор-граф — `pipeline_graph.py` (узлы N0–N7).

## LLM-промпты

| назначение | файл:строка | переменная | вход → выход |
|---|---|---|---|
| **ChemX MIC extraction** (главный): строки compound_id / target_value / units / bacteria | `chemx/scripts/extract_all.py:27,28` | `SYSTEM`, `P` | excerpts (Mathpix md) → JSON, 1 строка на (compound, bacterium) |
| IUPAC-имена для OPSIN | `chemx/smiles_router.py:62` | `SYS` (в `smiles_opsin`) | OCR-текст → {compound_id, iupac_name} → py2opsin → SMILES |
| OCSR через VLM (Claude-vision) | `chemx/smiles_router.py:157` | `SYS` (в `smiles_claude_vision`) | страницы-картинки → [{label, smiles}] |
| Общий structured extractor (домен-независимый) | `extraction/extractor.py:22,27` | `SYSTEM`, `SCHEMA_HINT` | текст → JSON records (entity_type, value, normalized, quantity, unit, quote, confidence) |
| Чтение фигур (figure → структура) | `ocr/figure_vision.py:10` | `_PROMPT` | картинка фигуры → {figure_type, entities, data_summary, key_finding} |

## Детерминированные узлы (НЕ LLM — by design)

| узел | файл:строка | логика |
|---|---|---|
| strategy router (OPSIN/PubChem/OCSR) | `chemx/smiles_router.py:35` | `classify_strategy()`: эвристика по плотности IUPAC-имён / drug-name (hits≥15 → opsin, иначе ocsr) |
| OCR-движок (pymupdf/Mathpix/Mistral) | `ocr/dispatch.py:33` | `route = force_engine or (mistral если scanned, иначе mathpix если math_tables, иначе pymupdf)` |

## Модель-оркестратор
`chemx/smiles_router.py:17` — `ORCH_MODEL` (env `SCINEX_ORCH_MODEL`, default `deepseek-direct`): text-reasoning для strategy classification, IUPAC-extraction, row/R-table extraction.

## Граф решений
`pipeline_graph.py` — узлы: N0 doc_type · N1 classify_pdf · N2 ingest (`ocr.dispatch`) · N3 figures (raster) · N4 strategy · N5 run (OPSIN/PubChem/OCSR-ensemble) · N6 coref · N7 gates. Каждый узел логирует `{decision, why, evidence}`.
