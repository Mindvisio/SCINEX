import sys, json, os
sys.path.insert(0,'/root/scinex')
from typing import List
from pydantic import BaseModel, Field
from lib.llm_clients import call_json
class Row(BaseModel):
    compound_id: str = Field(description='exact label e.g. 11a, 12e, 3b')
    target_type: str = Field(description='assay type, e.g. MIC or MBC')
    target_relation: str = Field(description='= or > or <')
    target_value: str = Field(description='numeric value as string')
    target_units: str = Field(description='units e.g. ug/mL')
    bacteria: str = Field(description='organism/strain name as written in the paper')
class Extract(BaseModel):
    rows: List[Row]
SYS='You extract antibacterial assay measurements from a medicinal-chemistry paper. Output every (compound, organism, value) cell from the activity tables (MIC/MBC). Use the paper\'s exact compound labels and organism names. Split ">256" into relation ">" and value "256". One row per compound-organism cell. Do not include the reference drug rows unless they have a compound label. Do not invent compounds.'
for stem in ['molecules27031103','ph16040516']:
    ocr=open('/root/scinex/chemx/results/ocr_%s.md'%stem).read()[:60000]
    user='Paper OCR follows. Extract ALL antibacterial activity measurements (every compound x organism cell from the MIC/MBC tables).\n\n'+ocr
    try:
        sr=call_json('claude-opus', user, Extract, system_prompt=SYS, max_tokens=8000, reasoning_effort='low', timeout=300)
        rows=[r.model_dump() for r in sr.parsed.rows]
        json.dump(rows, open('/root/scinex/chemx/results/llm_%s.json'%stem,'w'), ensure_ascii=False)
        import collections
        print('%-20s rows=%d compounds=%d  (%s)'%(stem,len(rows),len(set(r['compound_id'] for r in rows)),sr.model))
    except Exception as e:
        print('%-20s ERROR %s'%(stem,repr(e)[:160]))
