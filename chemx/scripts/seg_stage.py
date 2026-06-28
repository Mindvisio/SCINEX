import os, glob
import numpy as np, fitz
from PIL import Image
import decimer_segmentation as ds
PAPERS=['intechopen.108949','antibiotics10081002']
OUT='/home/ubuntu/scinex/chemx/crops'
def render(pdf, dpi=300):
    doc=fitz.open(pdf); out=[]; m=fitz.Matrix(dpi/72,dpi/72)
    for p in range(min(len(doc),20)):
        pix=doc[p].get_pixmap(matrix=m)
        img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
        if pix.n==4: img=img[:,:,:3]
        out.append(np.ascontiguousarray(img))
    return out
for stem in PAPERS:
    pdf='/home/ubuntu/scinex/chemx/pdfs/%s.pdf'%stem
    d=os.path.join(OUT,stem); os.makedirs(d, exist_ok=True)
    for f in glob.glob(d+'/*.png'): os.remove(f)
    pages=render(pdf); nseg=0
    for pi,arr in enumerate(pages):
        try: segs=ds.segment_chemical_structures(arr, expand=True)
        except Exception as e: print(stem,'pg',pi,'segerr',repr(e)[:80], flush=True); continue
        for si,seg in enumerate(segs):
            try:
                im=Image.fromarray(seg)
                if im.width<60 or im.height<60: continue
                im.save('%s/p%02d_s%02d.png'%(d,pi,si)); nseg+=1
            except Exception: pass
    print('%-22s pages=%d segments=%d'%(stem,len(pages),nseg), flush=True)
print('SEG_DONE', flush=True)
