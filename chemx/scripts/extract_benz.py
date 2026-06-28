import sys, json, re
sys.path.insert(0,'/root/scinex')
from ocr.mathpix import pdf_to_markdown
from lib.llm_clients import call_json
from pydantic import BaseModel
from typing import List

class Row(BaseModel):
    compound_id: str; target_type: str; target_relation: str
    target_value: str; target_units: str; bacteria: str
class Rows(BaseModel):
    rows: List[Row]

def focus(md):
    """табличные блоки + по ~4 строки контекста (подпись/юниты) + keyword-строки"""
    L=md.splitlines(); keep=set()
    kw=re.compile(r'(mic|minimum inhibitory|\u00b5g|\u03bcg|\u00b5m|\u03bcm|inhibitory concentration|atcc|mtcc|strain|escherichia|aureus|pseudomonas|subtilis|antibacterial)', re.I)
    intable=[i for i,x in enumerate(L) if x.strip().startswith('|')]
    its=set(intable)
    for i in intable:
        for j in range(i-4,i+2): 
            if 0<=j<len(L): keep.add(j)
    for i,x in enumerate(L):
        if kw.search(x):
            for j in range(i-1,i+2):
                if 0<=j<len(L): keep.add(j)
    out=[]; prev=-2
    for i in sorted(keep):
        if i>prev+1: out.append('...')
        out.append(L[i]); prev=i
    return '\n'.join(out)

SYSTEM=("You extract antibacterial MIC data from a chemistry paper. Output ONLY JSON. Never invent; only rows present in the text/tables.")
P="""From the excerpts below (Mathpix markdown, pipe-tables preserved), extract EVERY antibacterial Minimum Inhibitory Concentration (MIC) value, ONE row per (compound, bacterium) cell.
Rules:
- compound_id: compound label EXACTLY as printed (e.g. 31a, 7b); strip markdown asterisks. Use the compound/code column.
- SKIP standard drug controls (ciprofloxacin/cipro, fluconazole/flu, ampicillin, gentamicin, streptomycin, norfloxacin, paclitaxel/PTX) and reference rows.
- bacteria: the bacterium for that column, verbatim as labeled (e.g. EC, PA, MRSA, or full species).
- target_value: MIC number exactly as printed (e.g. 16, 0.5, 0,056). If range or > / <, put the number and set target_relation.
- target_units: unit as printed (e.g. "\u00b5g mL-1", "\u00b5M"); if the cell omits it, infer from caption/surrounding text.
- target_relation: "=" normally; ">" or "<" if value like >256.
- target_type: "MIC" (or "pMIC" if paper reports pMIC/negative-log).
- ONLY antibacterial MIC. SKIP antifungal, anticancer, MBC, MFC, IC50, zone-of-inhibition. Skip ND/empty/"-".
Return JSON {{"rows":[{{"compound_id":..,"target_type":..,"target_relation":..,"target_value":..,"target_units":..,"bacteria":..}}]}}

=== EXCERPTS ===
{md}"""

pdf=sys.argv[1]; name=sys.argv[2]
md=focus(pdf_to_markdown(pdf))
open('/tmp/chemx_benz/focus_%s.txt'%name,'w').write(md)
sr=call_json("deepseek-v4-pro", P.format(md=md), Rows, system_prompt=SYSTEM, temperature=0.0, max_tokens=14000)
rows=[r.model_dump() for r in sr.parsed.rows]
json.dump(rows, open('/tmp/chemx_benz/llm_%s.json'%name,'w'), ensure_ascii=False, indent=1)
print('focus_len',len(md),'rows',len(rows))
from collections import Counter
print('bacteria',dict(Counter(r['bacteria'] for r in rows)))
print('units',dict(Counter(r['target_units'] for r in rows)))
for r in rows[:8]: print('  ',r)
