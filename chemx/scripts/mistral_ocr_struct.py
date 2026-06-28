import sys, base64, os, json
import httpx
key=os.environ["MISTRAL_API_KEY"]
pdf="/root/scinex/benchmarks/_cpb/10.1038_s41467-023-44625-w.pdf"
b64=base64.b64encode(open(pdf,"rb").read()).decode()
body={"model":"mistral-ocr-latest","document":{"type":"document_url","document_url":f"data:application/pdf;base64,{b64}"},"include_image_base64":False,"confidence_scores_granularity":"word"}
r=httpx.post("https://api.mistral.ai/v1/ocr",headers={"Authorization":f"Bearer {key}"},json=body,timeout=180)
d=r.json(); json.dump(d,open("/tmp/mistral_ocr_resp.json","w"))
p=d["pages"][1]
def short(x,n=320): return json.dumps(x,ensure_ascii=False)[:n]
print("confidence_scores:", short(p.get("confidence_scores")))
print("blocks count:", len(p.get("blocks") or []), "| first2:", short(p.get("blocks",[])[:2]))
imgs=p.get("images") or []
print("images count:", len(imgs), "| img[0] (no b64):", short({k:v for k,v in imgs[0].items() if k!='image_base64'}) if imgs else "none")
print("tables:", short(p.get("tables",[])[:1]))
print("dimensions:", p.get("dimensions"), "| header:", short(p.get("header")), "| footer:", short(p.get("footer")))
