import sys, json
sys.path.insert(0,'/root/scinex')
from typing import List
from pydantic import BaseModel, Field
from lib.llm_clients import call_json
class Row(BaseModel):
    compound_id: str; target_type: str; target_relation: str; target_value: str; target_units: str; bacteria: str
class Extract(BaseModel):
    rows: List[Row]
SYS='Extract every antibacterial assay measurement (each compound x organism cell) from the MIC/MBC activity tables. Use exact compound labels and organism names from the paper. Split ">256" into relation ">" value "256". One row per compound-organism-value cell. No invented compounds, no reference-drug-only rows.'
stem=sys.argv[1]
ocr=open('/root/scinex/chemx/results/ocr_%s.md'%stem).read()[:70000]
sr=call_json('claude-opus','Extract ALL antibacterial activity measurements:\n\n'+ocr, Extract, system_prompt=SYS, max_tokens=13000, reasoning_effort='low', timeout=290)
rows=[r.model_dump() for r in sr.parsed.rows]
json.dump(rows, open('/root/scinex/chemx/results/llm_%s.json'%stem,'w'), ensure_ascii=False)
print('%-20s rows=%d compounds=%d (%s)'%(stem,len(rows),len(set(r['compound_id'] for r in rows)),sr.model))
