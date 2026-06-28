import sys, json
sys.path.insert(0,'/root/scinex')
from rdkit import Chem
from rdkit import RDLogger; RDLogger.DisableLog('rdApp.*')
from lib.llm_clients import call_json
from pydantic import BaseModel
from typing import Dict

SCAFFOLD='[*:1]Nc1nnc(-c2ccc(-c3nc4cc(C)c(C)cc4[nH]3)cc2)s1'  # OCSR-derived Markush core

class RTable(BaseModel):
    rgroups: Dict[str, str]   # compound_id -> R SMILES fragment with [*:1]

SYSTEM=("You extract R-group substituents from a benzimidazole-thiadiazole SAR series. "
 "All compounds share ONE scaffold and differ only by the N-substituent R on the thiadiazole 2-amino nitrogen. "
 "For each compound id, determine R from the table AND reconcile with the descriptive prose (OCR of table images is noisy; prose is authoritative). "
 "Output JSON {\"rgroups\": {compound_id: R_smiles}} where R_smiles is a SMILES fragment with EXACTLY one attachment point [*:1] (bond to scaffold N). "
 "Examples: methyl [*:1]C ; ethyl [*:1]CC ; propyl [*:1]CCC ; isopropyl [*:1]C(C)C ; cyclohexyl [*:1]C1CCCCC1 ; 2-chloroethyl [*:1]CCCl ; 2-chlorophenyl [*:1]c1ccccc1Cl ; 4-methoxyphenyl [*:1]c1ccc(OC)cc1 .")

def region(md):
    L=md.split(chr(10)); return chr(10).join(L[54:130])
def enum(scaf, rs):
    rm=Chem.MolFromSmiles(rs)
    if rm is None: return None
    try: return Chem.MolToSmiles(Chem.molzip(scaf, rm))
    except Exception: return None

md=open('/root/scinex/chemx/results/ocr_acsomega.2c06142.md').read()
prompt=('Scaffold (R attaches at [*:1]): %s\n\nOCR table + text:\n%s\n\nReturn R SMILES fragment for every compound 5a..5h.'%(SCAFFOLD, region(md)))
sr=call_json('deepseek-v4-pro', prompt, RTable, system_prompt=SYSTEM, temperature=0.0, max_tokens=4000)
rt=sr.parsed
scaf=Chem.MolFromSmiles(SCAFFOLD)
gold={Chem.MolToSmiles(m) for m in (Chem.MolFromSmiles(s) for s in json.load(open('/root/gold_benz_acsomega.json'))) if m}
out={}
for cid, rs in rt.rgroups.items():
    smi=enum(scaf, rs)
    out[cid]={'r_smiles':rs,'smiles':smi,'in_gold':bool(smi and smi in gold)}
print('LLM', sr.model, '%.1fs'%sr.latency_s)
for cid in sorted(out):
    v=out[cid]; print(' ',cid, v['r_smiles'].ljust(20), (v['smiles'] or 'FAIL'), '<<GOLD' if v['in_gold'] else '')
rec={v['smiles'] for v in out.values() if v['in_gold']}
print('GOLD_UNIQ',len(gold),'ENUM_RECOVERED',len(rec),'/',len(gold))
json.dump(out, open('/root/scinex/chemx/results/rtable_acsomega.json','w'), indent=1)
print('SAVED rtable_acsomega.json')
