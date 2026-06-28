# Coverage vs AnswerThis (the "выдача" competitor)

## The honest model
"300M papers" (AnswerThis) and "500M" (our old deck) are both NAIVE SUMS of overlapping
sources. Real coverage = size of the DEDUPLICATED union (unique DOIs/IDs). We report that.

## AnswerThis (verified, May 2026)
Retrieves from 4 sources: **OpenAlex, Semantic Scholar, PubMed, arXiv** (paperguide review).
But PubMed (~38M) and arXiv (~2.4M) are near-subsets of OpenAlex (OpenAlex ingests both).
=> AnswerThis unique coverage ~= OpenAlex u Semantic Scholar (~290M-class), not 300M of distinct work.

## scinex source set
Backbone (same as theirs): OpenAlex + Semantic Scholar.
They do NOT have:
- **Europe PMC** (~43M) — biomed full text + preprints not all in OpenAlex.
- **CORE** (~290M+ records) — OA repositories, theses, institutional full text. Large UNIQUE pool.
- **Google Patents** (via SerpApi) — patents, a content class outside any of AnswerThis's 4 sources.
Also added (low marginal-unique, but in the deck + useful): Crossref (metadata), arXiv,
PubMed (MeSH/recency). Unpaywall = access RESOLVER (DOI->OA PDF for the extraction layer), not coverage.

## Verdict
scinex's deduplicated union is a STRICT SUPERSET of AnswerThis's open corpus
(their backbone + Europe PMC + CORE), plus patents (Lens) they lack entirely.
=> "coverage > AnswerThis" is structural, not a counting trick.

## How we report the number (do NOT quote the sum)
Fixed probe-query set -> fan out to all sources -> dedup by DOI+normalized-title -> count unique.
Report unique-union size + per-source unique contribution (the Venn). TODO: eval/coverage_probe.py.

## Source status
Keyless (ready): OpenAlex, Semantic Scholar, Europe PMC, Crossref, arXiv, PubMed.
Keyed: CORE (CORE_API_KEY, free); Google Scholar + Google Patents (SERPAPI_API_KEY).
Dropped from old deck: **Consensus** is a competitor product, not an API source.
Note: **PubChem** is a compound DB (chemistry/validation layer), NOT paper coverage — lives in extraction/.

## Staged TODO
- eval/coverage_probe.py: measure the real dedup union + per-source Venn.
- PubMed abstracts via efetch; Lens patent endpoint (/patent/search); structure-aware dedup (InChIKey).
