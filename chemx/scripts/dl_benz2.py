import os, json, re, urllib.request, urllib.parse, ssl
EMAIL=os.environ.get("UNPAYWALL_EMAIL",""); PROXY=os.environ.get("LLM_PROXY","")
DEST="/tmp/ChemX/LLM/data/pdfs/pdf_benzimidazole"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def _open(url, proxy=None, timeout=18, referer=None):
    hs={"User-Agent":UA,"Accept":"text/html,application/pdf,*/*","Accept-Language":"en-US,en;q=0.9"}
    if referer: hs["Referer"]=referer
    a=[urllib.request.HTTPSHandler(context=ctx)]
    if proxy: a.append(urllib.request.ProxyHandler({"http":proxy,"https":proxy}))
    return urllib.request.build_opener(*a).open(urllib.request.Request(url, headers=hs), timeout=timeout)
def fb(url, **kw): return _open(url, **kw).read()
def try_pdf(url, referer=None):
    for proxy in (None, PROXY or None):
        try:
            d=fb(url, proxy=proxy, timeout=20, referer=referer)
            if d[:5]==b"%PDF-": return d
        except Exception: pass
    return None
def unpay_locs(doi):
    try: d=json.loads(fb("https://api.unpaywall.org/v2/%s?email=%s"%(doi,EMAIL), timeout=20).decode())
    except Exception: return []
    out=[]
    for l in (d.get("oa_locations") or []):
        for k in ("url_for_pdf","url"):
            if l.get(k): out.append(l[k])
    return out
def epmc(doi):
    try:
        q="https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:%22"+urllib.parse.quote(doi)+"%22&format=json"
        d=json.loads(fb(q, timeout=20).decode())
        for r in d.get("resultList",{}).get("result",[]):
            if r.get("pmcid"): return "https://europepmc.org/articles/%s?pdf=render"%r["pmcid"]
    except Exception: pass
    return None
def landing(doi):
    try:
        resp=_open("https://doi.org/"+doi, timeout=25); final=resp.geturl(); html=resp.read().decode("utf-8","ignore")
    except Exception: return []
    c=[]
    for m in re.findall(r'citation_pdf_url["\'][^>]*content=["\']([^"\']+)', html): c.append(urllib.parse.urljoin(final,m))
    for m in re.findall(r'href=["\']([^"\']+)["\']', html):
        if ".pdf" in m.lower() or "/pdf" in m.lower(): c.append(urllib.parse.urljoin(final,m))
    seen=set(); o=[]
    for x in c:
        if x not in seen: seen.add(x); o.append(x)
    return o[:5]
targets=[("antibiotics12071220","10.3390/antibiotics12071220"),("antibiotics10081002","10.3390/antibiotics10081002"),("acsomega.2c06142","10.1021/acsomega.2c06142"),("RJC.2023.1638382","10.31788/RJC.2023.1638382"),("2023.12.si5a.0471","10.48047/ecb/2023.12.si5a.0471")]
for name,doi in targets:
    dest=os.path.join(DEST,name+".pdf")
    if os.path.exists(dest) and os.path.getsize(dest)>10000: print("SKIP",name,flush=True); continue
    data=None; via=None
    ep=epmc(doi)
    if ep: data=try_pdf(ep); via=ep if data else None
    if not data:
        for u in unpay_locs(doi):
            data=try_pdf(u, referer="https://doi.org/"+doi)
            if data: via=u; break
    if not data:
        for u in landing(doi):
            data=try_pdf(u, referer="https://doi.org/"+doi)
            if data: via=u; break
    if data: open(dest,"wb").write(data); print("OK",name,len(data),"<-",via[:70],flush=True)
    else: print("FAIL",name,doi,flush=True)
print("DONE",flush=True)
