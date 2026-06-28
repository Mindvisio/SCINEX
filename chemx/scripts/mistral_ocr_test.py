import sys, base64, os, time, json
import httpx
key = os.environ.get("MISTRAL_API_KEY")
if not key: print("NO KEY"); sys.exit()
pdf = "/root/scinex/benchmarks/_cpb/10.1038_s41467-023-44625-w.pdf"
b64 = base64.b64encode(open(pdf, "rb").read()).decode()
body = {
  "model": "mistral-ocr-latest",
  "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"},
  "include_image_base64": False,
  "confidence_scores_granularity": "word",
}
t0 = time.time()
try:
    r = httpx.post("https://api.mistral.ai/v1/ocr", headers={"Authorization": f"Bearer {key}"}, json=body, timeout=180)
except Exception as e:
    print("REQ ERR:", type(e).__name__, str(e)[:150]); sys.exit()
print(f"status={r.status_code} {time.time()-t0:.1f}s")
if r.status_code != 200:
    print(r.text[:600]); sys.exit()
d = r.json()
print("model:", d.get("model"), "| usage:", d.get("usage_info"))
pages = d.get("pages", [])
print("page[0] keys:", list(pages[0].keys()) if pages else "none")
text = "\n".join(p.get("markdown", "") for p in pages)
print(f"pages={len(pages)} total_md_chars={len(text)}")
for p in pages[:4]:
    wc = p.get("word_confidence_scores") or p.get("word_confidences") or []
    print(f"  p{p.get('index')}: avg={p.get('average_page_confidence_score')} min={p.get('minimum_page_confidence_score')} imgs={len(p.get('images',[]))} words={len(wc)}")
for p in pages:
    wc = p.get("word_confidence_scores") or p.get("word_confidences") or []
    if wc:
        print("  sample word-conf:", json.dumps(wc[:3], ensure_ascii=False)[:200]); break
print("--- md head ---")
print(text[:280])
