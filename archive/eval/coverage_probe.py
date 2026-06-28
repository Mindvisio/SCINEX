"""Real deduplicated coverage probe (the Venn), not the naive index-size sum. See COVERAGE.md.

Fans a fixed probe-query set to every source, keys results by DOI, reports:
- total unique DOIs (union); per-source returned / with-doi / unique-only;
- AnswerThis backbone (OpenAlex u S2 u PubMed u arXiv) vs scinex full union + delta.

Caveats: SAMPLE over probes x top-k (per-query retrieval coverage, not total index size).
DOI-less records (common in arXiv/CORE) are excluded from the DOI union => their unique
contribution is UNDERCOUNTED (conservative). Rate-limited sources (429) -> fewer hits.
Run: bash -c 'set -a; source /root/.api_keys; set +a; cd /root/scinex; python3 -m eval.coverage_probe'
"""
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retrieval.registry import build_sources, source_status  # noqa: E402

PROBES = [
    "graphene oxide synthesis",
    "DFT B3LYP reaction barrier",
    "perovskite solar cell efficiency",
    "metal organic framework CO2 capture",
    "rapamycin lifespan extension",
    "single cell RNA sequencing atlas",
    "transformer attention mechanism",
]
ANSWERTHIS = {"OpenAlex", "Semantic Scholar", "PubMed", "arXiv"}
K = 25


def _doi(d):
    d = (d or "").lower().strip().replace("https://doi.org/", "")
    return d or None


async def _probe(source, query):
    try:
        r = await source.search(query, max_results=K)
        papers = r.papers or []
        dois = {_doi(p.doi) for p in papers if _doi(p.doi)}
        return len(papers), dois, r.error
    except Exception as e:
        return 0, set(), str(e)


async def main():
    print("source status:", source_status())
    sources = build_sources()
    returned = defaultdict(int)
    doiset = defaultdict(set)
    errs = defaultdict(int)
    for q in PROBES:
        res = await asyncio.gather(*[_probe(s, q) for s in sources])
        for s, (n, dois, err) in zip(sources, res):
            returned[s.name] += n
            doiset[s.name] |= dois
            if err:
                errs[s.name] += 1
    names = [s.name for s in sources]
    union = set().union(*doiset.values()) if doiset else set()
    print(f"\nprobes: {len(PROBES)}  top-k: {K}")
    print(f"TOTAL UNIQUE DOIs (union of all sources): {len(union)}\n")
    print(f"{'source':18s} {'returned':>8} {'with-doi':>8} {'unique':>7} {'errs':>5}")
    for name in sorted(names, key=lambda n: -len(doiset[n])):
        others = set().union(*[doiset[m] for m in names if m != name]) if len(names) > 1 else set()
        uniq = doiset[name] - others
        print(f"{name:18s} {returned[name]:>8} {len(doiset[name]):>8} {len(uniq):>7} {errs[name]:>5}")
    at = set().union(*[doiset[n] for n in ANSWERTHIS if n in doiset]) if doiset else set()
    extra = union - at
    print(f"\nAnswerThis backbone (OpenAlex u S2 u PubMed u arXiv): {len(at)} unique DOIs")
    print(f"scinex full union:                                   {len(union)} unique DOIs")
    pct = 100 * len(extra) / max(1, len(at))
    print(f"  -> +{len(extra)} DOIs beyond the AnswerThis backbone ({pct:.1f}% more)")
    contrib = {n: len(doiset[n] & extra) for n in names if n not in ANSWERTHIS}
    contrib = {k: v for k, v in sorted(contrib.items(), key=lambda x: -x[1]) if v}
    print(f"  sources adding that extra: {contrib}")


if __name__ == "__main__":
    asyncio.run(main())
