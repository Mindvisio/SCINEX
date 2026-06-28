import sys, json, re
sys.path.insert(0,'/root/scinex')
from ocr.mathpix import pdf_to_markdown
from lib.llm_clients import call_json
from pydantic import BaseModel
from typing import List
class Row(BaseModel):
    compound_id:str; target_type:str; target_relation:str; target_value:str; target_units:str; bacteria:str
class Rows(BaseModel):
    rows: List[Row]
md=pdf_to_markdown("/tmp/ChemX/LLM/data/pdfs/pdf_benzimidazole/intechopen.108949.pdf")
kw=re.compile(r"(MIC|antibacterial|antimicrobial|minimum inhibitory|\u00b5g|\u03bcg|g/mL|g / mL)",re.I)
paras=[p for p in md.split("\n\n") if kw.search(p) and re.search(r"\d",p)]
focus="\n\n".join(paras)[:120000]
open('/tmp/chemx_benz/focus_intech.txt','w').write(focus)
SYSTEM="You extract antibacterial MIC values from a chemistry REVIEW. Output ONLY JSON. Never invent; only values stated in the text."
P="""Extract antibacterial Minimum Inhibitory Concentration (MIC) values from the REVIEW excerpts below. MIC data appears in PROSE (e.g. \"compound LIV showed antimicrobial MIC = 0.5 \u00b5g/mL\") and in small tables.
Rules:
- compound_id: copy EXACTLY as printed; it may be a Roman numeral (e.g. XLV, XLVI, LIV) or alphanumeric.
- If one MIC value is stated for a compound against several named bacteria, emit ONE row per bacterium.
- bacteria: the species named (e.g. \"E. coli\", \"S. aureus\", \"E.coli\"); copy as written.
- target_value: the MIC number exactly as printed (e.g. 6.25, 0.5).
- target_units: as printed (e.g. \u00b5g/mL).
- target_relation: \"=\" unless > / <.
- target_type: \"MIC\".
- ONLY antibacterial MIC. SKIP IC50, anticancer, antifungal, antiviral, anti-inflammatory, antimycobacterial, EC50, antitumour.
Return JSON {{"rows":[...]}}.
=== EXCERPTS ===
{md}"""
sr=call_json("deepseek-v4-pro", P.format(md=focus), Rows, system_prompt=SYSTEM, temperature=0.0, max_tokens=6000)
rows=[r.model_dump() for r in sr.parsed.rows]
json.dump(rows, open('/tmp/chemx_benz/llm_intechopen.108949.json','w'), ensure_ascii=False)
print('focus_len',len(focus),'rows',len(rows))
for r in rows[:15]: print("  ",r)
