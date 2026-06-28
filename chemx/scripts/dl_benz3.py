import os, json, re, urllib.request, urllib.parse, ssl
PROXY=os.environ.get("LLM_PROXY","")
DEST="/tmp/ChemX/LLM/data/pdfs/pdf_benzimidazole"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def _open(url, proxy=None, timeout=15, referer=None):
    hs={"User-Agent":UA,"Accept":"text/html,application/pdf,*/*"}
    if referer: hs["Referer"]=referer
    a=[urllib.request.HTTPSHandler(context=ctx)]
    if proxy: a.append(urllib.request.ProxyHandler({"http":proxy,"https":proxy}))
    return urllib.request.build_opener(*a).open(urllib.request.Request(url, headers=hs), timeout=timeout)
def fb(url, **kw): return _open(url, **kw).read()
def try_pdf(url, referer=None):
    for proxy in (None, PROXY or None):
        try:
            d=fb(url, proxy=proxy, timeout=18, referer=referer)
            if d[:5]==b"%PDF-": return d
        except Exception as e: pass
    return None
def crossref_links(doi):
    try: d=json.loads(fb("https://api.crossref.org/works/"+urllib.parse.quote(doi), timeout=15).decode())
    except Exception as e: print("  crossref err",str(e)[:50]); return [],None
    m=d.get("message",{}); out=[]
    for l in m.get("link",[]):
        if l.get("URL"): out.append(l["URL"])
    prim=(m.get("resource",{}).get("primary",{}) or {}).get("URL")
    return out, prim
def landing_scrape(url, doi):
    try:
        resp=_open(url, timeout=18); final=resp.geturl(); html=resp.read().decode("utf-8","ignore")
    except Exception as e: print("  landing err",str(e)[:50]); return []
    c=[]
    for mm in re.findall(r'citation_pdf_url["\'][^>]*content=["\']([^"\']+)', html): c.append(urllib.parse.urljoin(final,mm))
    for mm in re.findall(r'href=["\']([^"\']+)["\']', html):
        if ".pdf" in mm.lower(): c.append(urllib.parse.urljoin(final,mm))
    s=set(); o=[]
    for x in c:
        if x not in s: s.add(x); o.append(x)
    return o[:6]
for name,doi in [("RJC.2023.1638382","10.31788/RJC.2023.1638382"),("2023.12.si5a.0471","10.48047/ecb/2023.12.si5a.0471")]:
    print("==",name,doi)
    links,prim=crossref_links(doi); print("  crossref links:",links[:4],"| primary:",prim)
    data=None; via=None
    for u in links:
        data=try_pdf(u, referer="https://doi.org/"+doi)
        if data: via=u; break
    if not data and prim:
        for u in landing_scrape(prim, doi):
            print("  cand:",u[:80]); data=try_pdf(u, referer=prim)
            if data: via=u; break
    if data: open(os.path.join(DEST,name+".pdf"),"wb").write(data); print("  OK",len(data),"<-",via[:70])
    else: print("  FAIL")
