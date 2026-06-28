# export (core pipeline stage) — TODO

records + review -> deliverables:
- md / TeX  : GENERATE from records + review (distinct from ocr/mathpix which goes PDF -> md).
- docx / pdf: render via pandoc (md->docx/pdf) or the docx/pdf skills; TeX->pdf via tectonic/latexmk.
- csv / json: flatten ExtractedRecord list (row per record: paper, entity_type, value,
  normalized*, unit, span.quote, confidence, validation).

Interface (planned): to_json(records); to_csv(records); to_markdown(review, records);
to_tex(review, records); render(md_or_tex, fmt="docx"|"pdf").
