"""Build the ChemPaperBench corpus index (and optionally the typed CorpusStore) from DOI-named PDFs
in benchmarks/_cpb/.
  10.1038_s41565-019-0465-3.pdf -> DOI 10.1038/s41565-019-0465-3 (matched via the benchmark CSV).
Per PDF: ocr.pdf_extract -> corpus dict -> index.build_index -> save.
With --store: ALSO run the LLM extractor per paper -> ExtractedRecords -> store.build_store ->
_store.json (the substrate). --ocsr additionally reads figure structures (DECIMER+vision). Run in
.venv with keys sourced:
    bash -c 'set -a; source /root/.api_keys; set +a; .venv/bin/python eval/build_corpus.py --store'
"""
from __future__ import annotations
import csv, glob, json, os, re, sys
sys.path.insert(0, "/root/scinex")
from ocr.pdf_extract import extract_pdf
from index.index import build_index
from store.enrich import classify_data_relevance

CPB = "/root/scinex/benchmarks/_cpb"
CSV = f"{CPB}/chempaperbench.csv"


def _canon(s):
    return re.sub(r'[^a-z0-9]', '', (s or "").lower())


def doi_map():
    """canon(doi) -> {doi, title}; multi-DOI paper_link cells split so each DOI maps. Canonical keys
    (alphanumeric-only, lowercased) absorb filename-sanitization (/, parens, ; ...) differences."""
    m = {}
    with open(CSV) as f:
        for row in csv.DictReader(f):
            for tok in re.split(r'[;,\s]+', str(row["paper_link"])):
                doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', tok).strip()
                if "10." not in doi:
                    continue
                key = _canon(doi)
                if key and key not in m:
                    m[key] = {"doi": doi, "title": row.get("paper_name")}
    return m


def build(pdf_dir=CPB, index_out=f"{CPB}/_index", corpus_out=f"{CPB}/_corpus.json",
          with_store=False, with_ocsr=False, with_enrich_llm=False, with_enrich_db=False, with_grobid=False, with_enrich_vision=False, store_out=f"{CPB}/_store.json"):
    m = doi_map()
    pdfs = sorted(glob.glob(f"{pdf_dir}/*.pdf"))
    if not pdfs:
        print("no PDFs in", pdf_dir); return
    from extraction.schema import PaperRef
    store_records, store_assets, store_papers = [], [], []
    pdf_by_doi = {}
    domain = None
    if with_store:
        from extraction.extractor import extract_records
        from domains.base import get as get_domain
        domain = get_domain("chemistry")

    corpus = []
    for p in pdfs:
        stem = os.path.splitext(os.path.basename(p))[0]
        info = m.get(_canon(stem))
        doi = info["doi"] if info else stem.replace("_", "/", 1)
        title = info["title"] if info else None
        pdf_by_doi[doi] = p
        try:
            ext = extract_pdf(p, fig_dir=f"{CPB}/_figures/{stem}")
        except Exception as e:
            print(f"  EXTRACT FAIL {stem}: {type(e).__name__}: {e}", flush=True); continue
        for fig in ext.get("figures", []) or []:
            fig["data_relevance"] = classify_data_relevance(fig.get("caption") or "")
        corpus.append({"paper_id": doi, "doi": doi, "title": title,
                       "text": ext["text"], "figures": ext["figures"], "tables": ext["tables"]})
        print(f"  {stem}: text={len(ext['text'])} figs={len(ext['figures'])} tabs={len(ext['tables'])}", flush=True)

        if with_store:
            paper = PaperRef(paper_id=doi, doi=doi, title=title)
            store_papers.append(paper)
            try:
                recs = extract_records(ext["text"], paper, domain=domain)
                recs = [domain.validate(r) for r in recs]      # RDKit canon -> InChIKey -> PASSED
            except Exception as e:
                print(f"    extract_records FAIL {stem}: {type(e).__name__}: {e}", flush=True); recs = []
            if with_ocsr and ext["figures"]:
                try:
                    from domains.chemistry import molecules_from_figures
                    recs += molecules_from_figures(ext["figures"], paper)
                except Exception as e:
                    print(f"    ocsr FAIL {stem}: {type(e).__name__}: {e}", flush=True)
            store_records += recs
            for fig in ext["figures"]:
                store_assets.append({**fig, "paper_id": doi})
            for tab in ext["tables"]:
                store_assets.append({**tab, "paper_id": doi})
            print(f"    store: +{len(recs)} records", flush=True)

    # build store FIRST so figure enrichment (data_relevance + entity labels) feeds the index meta
    store = None
    if with_store:
        from store.build import build_store
        from store.enrich import enrich_assets, enrich_assets_llm
        store = build_store(store_records, assets=store_assets, papers=store_papers)
        esumm = (enrich_assets_llm if with_enrich_llm else enrich_assets)(store)
        print(f"  figure enrich ({'llm' if with_enrich_llm else 'keyword'}): {esumm}", flush=True)
        if with_enrich_db:
            from store.enrich_entities import enrich_entities
            print(f"  entity enrich (pubchem+nist): {enrich_entities(store)}", flush=True)
        if with_enrich_vision:
            from store.enrich import enrich_assets_vision
            print(f"  figure vision (gemini): {enrich_assets_vision(store)}", flush=True)
        if with_grobid:
            from ocr.grobid import is_alive, document_structure
            if not is_alive():
                print("  grobid: service unreachable -- skipping sections/references", flush=True)
            else:
                nsec = nref = 0
                for pid, pn in store.papers.items():
                    pdf = pdf_by_doi.get(pid)
                    if not pdf:
                        continue
                    ds = document_structure(pdf)
                    pn.sections = ds["sections"]
                    own = _canon(pn.doi or pid)
                    pn.references = [d for d in ds["references"] if _canon(d) != own]   # drop self-cite
                    nsec += len(pn.sections); nref += len(pn.references)
                print(f"  grobid: sections={nsec} refs={nref} over {len(store.papers)} papers", flush=True)
        amap = {(a.paper_id, a.node_id): a for a in store.assets}
        for paper in corpus:
            pid = paper["paper_id"]
            for fig in paper.get("figures", []) or []:
                a = amap.get((pid, fig.get("fig_id")))
                if a:
                    fig["data_relevance"] = a.data_relevance or fig.get("data_relevance")
                    fig["entities"] = [store.entities[nid].label for nid in (a.entities or [])
                                       if nid in store.entities]

    meta = [{k: v for k, v in c.items() if k != "text"} | {"text_len": len(c["text"])} for c in corpus]
    json.dump(meta, open(corpus_out, "w"), ensure_ascii=False, indent=1)
    print(f"corpus papers: {len(corpus)} -> building index...", flush=True)
    idx = build_index(corpus)
    idx.save(index_out)
    print(f"INDEX saved: {len(idx.chunks)} chunks, vecs {idx.vecs.shape} -> {index_out}", flush=True)
    if store is not None:
        store.save(store_out)
        print(f"STORE saved: {store.stats()} -> {store_out}", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    with_store = "--store" in args
    with_ocsr = "--ocsr" in args
    with_enrich_llm = "--enrich-llm" in args
    with_enrich_db = "--enrich-db" in args
    with_grobid = "--grobid" in args
    with_enrich_vision = "--enrich-vision" in args
    pos = [a for a in args if not a.startswith("--")]
    pdf_dir = pos[0] if len(pos) > 0 else CPB
    out = pos[1] if len(pos) > 1 else f"{CPB}/_index"
    build(pdf_dir, out, with_store=with_store, with_ocsr=with_ocsr, with_enrich_llm=with_enrich_llm, with_enrich_db=with_enrich_db, with_grobid=with_grobid, with_enrich_vision=with_enrich_vision)
