import sys, json
sys.path.insert(0,'/root/scinex')
from typing import List
from pydantic import BaseModel, Field
from lib.llm_clients import call_json
from py2opsin import py2opsin
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
class Cmp(BaseModel):
    compound_id: str = Field(description='label e.g. 11a, 12e, 3b')
    iupac_name: str = Field(description='clean systematic IUPAC name, no markdown, no italics markers')
class Names(BaseModel):
    compounds: List[Cmp]
SYS='You read the experimental/characterization section of a med-chem paper and return, for each final target compound, its full systematic IUPAC name exactly as a name-to-structure parser (OPSIN) would accept. Strip markdown/italic markers. Keep stereodescriptors like (R)/(S). Only final labelled target compounds (e.g. 11a, 12e, 3b), not intermediates.'
stem=sys.argv[1]
ocr=open('/root/scinex/chemx/results/ocr_%s.md'%stem).read()[:75000]
sr=call_json('claude-opus','Extract {compound_id, iupac_name} for every final target compound:\n\n'+ocr, Names, system_prompt=SYS, max_tokens=7000, reasoning_effort='low', timeout=290)
def canon(s):
    try: m=Chem.MolFromSmiles(str(s)); return Chem.MolToSmiles(m) if m else None
    except: return None
out={}; ok=0
for c in sr.parsed.compounds:
    smi=py2opsin(c.iupac_name); cs=canon(smi) if smi else None
    if cs: out[c.compound_id.strip()]=cs; ok+=1
json.dump(out, open('/root/scinex/chemx/results/oxa_smiles_%s.json'%stem,'w'))
print('%-20s names=%d opsin_ok=%d (%s)'%(stem,len(sr.parsed.compounds),ok,sr.model))
