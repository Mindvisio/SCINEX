import os, json, urllib.request, ssl
EMAIL=os.environ.get("UNPAYWALL_EMAIL",""); PROXY=os.environ.get("LLM_PROXY","")
DEST="/tmp/ChemX/LLM/data/pdfs/pdf_benzimidazole"; os.makedirs(DEST, exist_ok=True)
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
pairs=[("antibiotics12071220","10.3390/antibiotics12071220"),("antibiotics10081002","10.3390/antibiotics10081002"),("acsomega.2c06142","10.1021/acsomega.2c06142"),("s41598-022-21435-6","10.1038/s41598-022-21435-6"),("intechopen.108949","10.5772/intechopen.108949"),("RJC.2023.1638382","10.31788/RJC.2023.1638382"),("2023.12.si5a.0471","10.48047/ecb/2023.12.si5a.0471"),("s13065-018-0479-1","10.1186/s13065-018-0479-1"),("d2ra06667j","10.1039/d2ra06667j")]
def get(url, proxy=None, timeout=25):
    hs={"User-Agent":UA,"Accept":"application/pdf,*/*"}
    a=[urllib.request.HTTPSHandler(context=ctx)]
    if proxy: a.append(urllib.request.ProxyHandler({"http":proxy,"https":proxy}))
    op=urllib.request.build_opener(*a)
    return op.open(urllib.request.Request(url, headers=hs), timeout=timeout).read()
def unpay(doi):
    d=json.loads(get("https://api.unpaywall.org/v2/%s?email=%s"%(doi,EMAIL), timeout=25).decode())
    loc=d.get("best_oa_location") or {}; return loc.get("url_for_pdf") or loc.get("url")
for name,doi in pairs:
    dest=os.path.join(DEST, name+".pdf")
    if os.path.exists(dest) and os.path.getsize(dest)>10000: print("SKIP",name,os.path.getsize(dest)); continue
    try: purl=unpay(doi)
    except Exception as e: print("UNPAY-FAIL",name,str(e)[:60]); continue
    if not purl: print("NO-OA-PDF",name,doi); continue
    data=None
    for proxy in (None, PROXY or None):
        try:
            d=get(purl, proxy=proxy, timeout=30)
            if d[:5]==b"%PDF-": data=d; break
        except Exception as e: pass
    if data: open(dest,"wb").write(data); print("OK",name,len(data),"<-",purl[:65])
    else: print("FAIL",name,"url=",purl[:65])
