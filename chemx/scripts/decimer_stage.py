import os, glob, json
from DECIMER import predict_SMILES
PAPERS=['intechopen.108949','antibiotics10081002']
OUT='/home/ubuntu/scinex/chemx/results'
for stem in PAPERS:
    crops=sorted(glob.glob('/home/ubuntu/scinex/chemx/crops/%s/*.png'%stem))
    raw=[]
    for i,c in enumerate(crops):
        try: smi=predict_SMILES(c)
        except Exception: smi=None
        raw.append({'crop':os.path.basename(c),'smiles':smi})
        if (i+1)%25==0: print('%s %d/%d'%(stem,i+1,len(crops)), flush=True)
    json.dump(raw, open('%s/decimer_raw_%s.json'%(OUT,stem),'w'))
    print('%-22s crops=%d got=%d'%(stem,len(crops),sum(1 for r in raw if r['smiles'])), flush=True)
print('DECIMER_DONE', flush=True)
