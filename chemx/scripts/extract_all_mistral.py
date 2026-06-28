import sys, json, re, time
sys.path.insert(0,'/root/scinex')
from ocr.mistral_ocr import extract_pdf_mistral
from lib.llm_clients import call_json
from pydantic import BaseModel
from typing import List
class Row(BaseModel):
    compound_id: str; target_type: str; target_relation: str; target_value: str; target_units: str; bacteria: str
class Rows(BaseModel):
    rows: List[Row]
def focus(md):
    L=md.splitlines(); keep=set()
    kw=re.compile(r'(mic|minimum inhibitory|\u00b5g|\u03bcg|\u00b5m|\u03bcm|inhibitory concentration|atcc|mtcc|strain|escherichia|aureus|pseudomonas|subtilis|klebsiella|bacillus|antibacterial|legend|abbreviation)', re.I)
    intab=[i for i,x in enumerate(L) if x.strip().startswith('|')]
    for i in intab:
        for j in range(i-5,i+2):
            if 0<=j<len(L): keep.add(j)
    for i,x in enumerate(L):
        if kw.search(x):
            for j in range(i-2,i+3):
                if 0<=j<len(L): keep.add(j)
    out=[]; prev=-2
    for i in sorted(keep):
        if i>prev+1: out.append('...')
        out.append(L[i]); prev=i
    return '\n'.join(out)
SYSTEM="You extract antibacterial MIC data from a chemistry paper. Output ONLY JSON. Never invent; only rows present in the text/tables."
P="""From the excerpts below (Mathpix markdown, pipe-tables preserved), extract EVERY antibacterial Minimum Inhibitory Concentration (MIC) value, ONE row per (compound, bacterium) cell.
Rules:
- compound_id: compound label EXACTLY as printed (e.g. 31a, 7b); strip markdown asterisks. Use the compound/code column.
- SKIP standard drug controls (ciprofloxacin/cipro, fluconazole/flu, ampicillin, gentamicin, streptomycin, norfloxacin, paclitaxel/PTX, chloramphenicol) and reference rows.
- bacteria: the bacterium for that column. If the table uses an abbreviation (EC, PA, SA, SF, MSSA, MRSA, BS, KP, ...), RESOLVE it to the FULL name with strain/ATCC designation EXACTLY as defined in the legend/caption/footnote (e.g. "Escherichia coli ATCC 25922"). If no legend, output the label as printed.
- target_value: MIC number exactly as printed (e.g. 16, 0.5, 0,056). If range or > / <, put the number and set target_relation.
- target_units: unit as printed (e.g. "\u00b5g mL-1", "\u00b5M"); if the cell omits it, infer from caption/surrounding text.
- target_relation: "=" normally; ">" or "<" if value like >256.
- target_type: "MIC" (or "pMIC" if paper reports pMIC/negative-log).
- ONLY antibacterial MIC. SKIP antifungal, anticancer, MBC, MFC, IC50, zone-of-inhibition. Skip ND/empty/"-".
Return JSON {{"rows":[{{"compound_id":..,"target_type":..,"target_relation":..,"target_value":..,"target_units":..,"bacteria":..}}]}}
=== EXCERPTS ===
{md}"""
PAPERS=['antibiotics12071220','antibiotics10081002','acsomega.2c06142','s41598-022-21435-6','intechopen.108949','s13065-018-0479-1','d2ra06667j']
DIR='/tmp/ChemX/LLM/data/pdfs/pdf_benzimidazole'
for name in PAPERS:
    t0=time.time()
    try:
        md=focus(extract_pdf_mistral(DIR+'/'+name+'.pdf')['text'])
        sr=call_json("deepseek-v4-pro", P.format(md=md), Rows, system_prompt=SYSTEM, temperature=0.0, max_tokens=22000)
        rows=[r.model_dump() for r in sr.parsed.rows]
        json.dump(rows, open('/tmp/chemx_benz/llm_mistral_%s.json'%name,'w'), ensure_ascii=False)
        print('%-22s rows=%-4d focus=%-6d %.0fs'%(name,len(rows),len(md),time.time()-t0), flush=True)
    except Exception as e:
        print('%-22s ERROR %s'%(name,str(e)[:80]), flush=True)
print('ALLDONE', flush=True)
