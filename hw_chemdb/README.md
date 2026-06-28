# hw_chemdb — сборка химической БД из PDF без генеративного LLM

Домашнее задание к лекции *«Анализ, очистка и стандартизация химических данных»*: на вход — папка
с PDF научных статей, на выходе — **курированная БД в CSV** + отчёт об обработке. Конвейер без
генеративного LLM: только предметные инструменты — детерминированные (OPSIN, RDKit, pint, PubChem)
и специализированные обученные модели распознавания (**OpenChemIE**: MolDetect, MolScribe, RxnScribe,
ChemRxnExtractor), не chat-LLM. Модуль встроен в `scinex` и переиспользует его кирпичи
(`ocr/pdf_extract.py`, `ocr/ocsr.py`, `enrich/pubchem.py`).

## Конвейер

```
PDF ─┬─ текст    ── regex (IC50/EC50/Ki/Kd/MIC/solubility/mp/logP/yield) + inline SMILES/InChI
     │             + OPSIN-скан систематических имён (даёт структуру)
     │             + ChemRxnExtractor: prep/yield-события «соединение N → выход Y%»
     ├─ таблицы  ── разбор колонок «соединение × свойство(единица)» → измерения
     └─ фигуры   ── OpenChemIE coref: MolDetect (детекция) + MolScribe (структура) +
                    привязка молекула↔идентификатор (обученный coreference)
                          │  scaffold_graft.resolve_coref: markush «*» → конкретная молекула
                          │  числовая метка → join к строкам активности из таблиц/текста
                          │
   стандартизация ────────┤  единицы → канон (pint): IC50→nM, solubility→g/L, T→°C, MW→g/mol, %
                          │  категории → словарь: assay_type, organism
   резолвинг id ──────────┤  SMILES→RDKit canon+InChIKey; имя→OPSIN; cross-id→PubChem (CID/CAS/формула/MW/IUPAC)
   валидация ─────────────┤  passed | unverified | failed
   дедупликация ──────────┤  InChIKey→CID→CAS, fuzzy по имени (RapidFuzz); 5 уровней; тегирование, не удаление
   конфликты ─────────────┤  одно соединение+свойство, расходящиеся значения → conflict_group (метаданные, без усреднения)
   → CSV + processing_report.md
```

Ключевой принцип лекции выдержан: **сырое значение сохраняется всегда**, рядом — стандартизованное
и правило пересчёта; то, что нельзя разрешить автоматически (торговые названия, метки `7b`, измерение
без явного соединения, конфликт значений, dummy-capped структура), **не выдумывается**, а помечается
в очередь ручной проверки (`needs_review` + `review_reason`).

## Почему OpenChemIE (и почему это всё ещё «без LLM»)

Распознавание структур из фигур — главная сложность. Геометрический эвристик «структура → метка под
ней» проваливается: метки соединений вшиты в графику и часто это имена или markush-таблицы.
**OpenChemIE** даёт обученный *coreference* молекула↔идентификатор и на 8 статьях восстановил
**40 числовых привязок** против 3 у эвристика. Это не chat-LLM, а конвейер узких моделей
(детектор + OCSR + NER-BERT), сравнимый по духу с MolScribe/OPSIN — без генерации и галлюцинаций
текста. Сам SMILES всегда арбитрится RDKit.

| Этап | Инструмент | Тип |
|---|---|---|
| PDF → текст/таблицы | PyMuPDF / pymupdf4llm | парсер, offline |
| фигуры → структуры + метки | **OpenChemIE** (MolDetect + MolScribe + coref) | обученные модели распознавания |
| реакции/выходы из текста | **ChemRxnExtractor** (BERT-теггер ролей) | обученная модель NER |
| реакционные схемы из фигур | **RxnScribe** (в составе OpenChemIE) | обученная модель |
| markush «*» → конкретная молекула | **scaffold_graft** (RDKit cap_dummies / molzip) | детерминированный |
| имя → структура | **OPSIN** (`py2opsin`) | детерминированный грамматический разбор |
| структура (канон/InChIKey/валидация) | **RDKit** | детерминированный |
| OCSR (standalone путь, + TTA) | **MolScribe** (+ **DECIMER** для сверки) | модели распознавания |
| свойства из текста | regex + ассоциация ближайшего соединения | детерминированный |
| единицы | **pint** (с молярностью) | детерминированный |
| cross-id (CID/CAS/формула/MW/IUPAC) | **PubChem PUG-REST** | запрос к БД |
| record linkage | **RapidFuzz** | строковое сходство |

**TTA для полициклики** (`ocr/ocsr.py`): структуры со статусом не-`ok` ретраятся под аугментацией
(up2 + rot90 + rot270, без rot180 — эмпирически худший) с majority-vote по InChIKey. Вытаскивает
часть сросшихся ядер, которые OCSR не берёт в исходной ориентации (напр. налтриндол); даёт
бесплатную уверенность и отсекает выбросы. Платится только на тяжёлом подмножестве.

**scaffold-graft для SAR-серий**: coref-вывод OpenChemIE на SAR-сериях — это ядро + конкретный R с
«*» как артефактом открытой валентности. `resolve_coref` капчет `*`→H в специфичную молекулу
(проверено: `8`→ацетамидо, `4`→нитрил…), обходя OCSR сросшегося ядра вообще. `graft` (molzip)
сшивает ядро[*]+R[*], когда R дан отдельной колонкой таблицы. Grafted-структуры → `review`.

*ChemDataExtractor2* (`--cde`) — опционально, по умолчанию выключен (в текущей сборке ломается
POS-теггер `legacy_pos_tag`); его роль закрывают OPSIN-скан и ChemRxnExtractor.

## Запуск

```bash
# sci-node, отдельные venv: .venv основной; .venv-openchemie — OpenChemIE (torch+TF);
#                           .venv-molscribe / .venv-decimer — standalone OCSR
cd /root/scinex
.venv/bin/python -m hw_chemdb.pipeline --pdf-dir /path/to/pdfs --out chem_db.csv --reactions
```

OpenChemIE-путь включён по умолчанию (рендерит страницы сам, в обход битого layoutparser-парсера
фигур; модели грузятся в воркере-субпроцессе, тяжёлый venv не входит в runtime).

Флаги: `--reactions` включить ChemRxnExtractor (prep/yield из текста; **медленно**, ~4 мин/статью с
экспериментальной частью); `--no-openchemie` отключить figure/coref-путь; `--schemes` legacy-слой
DECIMER-Segmentation (вытеснен OpenChemIE); `--cde` ChemDataExtractor2; `--no-enrich` без PubChem;
`--no-molscribe`/`--no-decimer`/`--all-figures` — для standalone-OCSR.

## Выход

- **`chem_db.csv`** — все записи с тегами (полная провенанс-таблица, ничего не теряется).
- **`chem_db.dedup.csv`** — только первичные строки групп дублей (компактный вид для анализа).
- **`processing_report.md`** — отчёт: счётчики записей/дублей/конфликтов/ручной проверки, разбивка по
  валидации/источнику/экстрактору, топ проблем, записи на PDF.

### Схема CSV (одна строка = одно наблюдение «соединение–свойство» или упоминание соединения)

`record_id` · провенанс: `source_pdf, source_page, source_type{text|table|figure}, extractor, evidence` ·
соединение: `name_raw, name_std, smiles_raw, smiles_canonical, inchikey, pubchem_cid, cas, formula,
mw, iupac_name` · контекст: `target_raw, assay_type_raw, assay_type_std, organism_raw, organism_std` ·
измерение: `property, value_raw, unit_raw, value_std, unit_std, conversion_note` ·
валидация: `validation, validation_detail` · дедуп/конфликт: `dup_group, dup_level, is_primary,
conflict_group, conflict_flag` · ревью: `needs_review, review_reason` · `extracted_at`.

`extractor` показывает источник структуры/измерения: `openchemie:coref` (фигура с меткой),
`openchemie:moldet` (фигура без метки), `openchemie:chemrxn` (yield из текста), `table`, `regex`,
`opsin`, а `table+openchemie` / `regex+openchemie` — строки активности, у которых структура
подставлена join-ом по номеру.

## Эмпирика (прогон на 8 med-chem статьях, опиоиды/NPS/каннабиноиды)

| метрика | значение |
|---|---|
| структур распознано (InChIKey) | 190 |
| **строк активности заполнено join-ом по номеру** | **20** (эвристик давал 3) |
| **полных триплетов структура+свойство+значение** | **22** (scheme-слой давал ~7) |
| yield-событий (ChemRxnExtractor) | 25 |
| conflict-групп | 9 |
| на ручной проверке | 291 |

Примеры собранных автоматически триплетов: compound 12 → Ki 22 nM + IC50 5 nM; compound 2 →
Ki 30 nM + IC50 140 nM (CID 130187413); 5a → Ki 760 nM + logP 4.0 (CID 5361092).

## Замечания и ограничения

- **Join по номеру бьёт по нумерованным статьям.** Где соединения в фигурах подписаны числами —
  coref сшивает структуру с активностью (20 строк). Где подписаны именами или нарисованы markush-
  таблицей (naltrexamine, NPS) — join почти не срабатывает; известные соединения всё равно
  резолвятся по InChIKey→PubChem.
- **Полициклика (сросшиеся ядра).** OCSR пиксельно ненадёжен (морфинановый кейдж даёт вырожденный
  SMILES). Митигируется TTA (часть вытаскивается) и scaffold-graft (для SAR обходит ядро). Димеры
  (norBNI) и самое сложное — честный флаг `failed`/`review`, не мусор.
- **markush «*».** `resolve_coref` капчет открытую валентность в конкретную молекулу, но `*` иногда
  означает внешний R из таблицы — поэтому все dummy-capped → `review` («verify R»).
- **Имена-идентификаторы** (`7b`, `compound 9`) не резолвятся по имени (PubChem вернёт мусор); идут
  на сшивку со структурой через join. Текст-майненные research-коды без записи в PubChem остаются
  неразрешёнными (фундаментальный предел, не баг).
- **Не все join-строки имеют значение**: структура привязалась, а число — компаратор (`>10000`) или
  артефакт ячейки → `value_std` пуст.
- **Связка свойство↔соединение в сплошном тексте** — эвристика (ближайшая метка в окне); надёжный
  источник — таблицы и фигуры, текстовые regex честно помечаются на ревью без привязки.
- **PubChem**: вежливый интервал ~0.2 c + кэш в пределах запуска (воспроизводимо).

## Файлы

```
hw_chemdb/
  record.py            схема строки (контракт CSV)
  detect.py            SMILES/InChI-детекторы, разбор заголовка «свойство (единица)»
  extract_text.py      regex-майнер свойств + inline-структуры + OPSIN-скан (+ опц. CDE)
  extract_tables.py    разбор markdown-таблиц PyMuPDF в измерения
  extract_openchemie.py OpenChemIE figure/coref + ChemRxnExtractor → записи + label-map + join   ← основной
  scaffold_graft.py    cap_dummies / molzip-graft / resolve_coref (markush «*» → молекула)
  extract_figures.py   standalone OCSR-обёртка (MolScribe+DECIMER)        # используется без OpenChemIE
  extract_schemes.py   [legacy] DECIMER-Segmentation scheme-слой          # вытеснен OpenChemIE
  standardize.py       единицы (pint) + категориальные словари
  resolve.py           OPSIN / RDKit / PubChem cross-id + кэш
  dedup.py             5-уровневая дедупликация (InChIKey + fuzzy)
  conflicts.py         детектор конфликтов значений (метаданные)
  report.py            отчёт об обработке
  pipeline.py          оркестратор + CLI
ocr/
  openchemie_worker.py OpenChemIE-воркер (свой venv): coref + ChemRxnExtractor → JSON
  ocsr.py              OCSR-консенсус (MolScribe+DECIMER) + TTA-rescue
  molscribe_worker.py / decimer_worker.py / decimer_seg_worker.py   воркеры OCSR (свои venv)
```