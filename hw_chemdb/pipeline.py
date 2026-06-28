"""Orchestrator + CLI for the no-LLM PDF -> chemical-database pipeline.

Stages (lecture slide 3):
  PDF -> extract (text regex+OPSIN | tables | figures OCSR) -> standardise (pint units + vocab)
      -> resolve (OPSIN name->structure | RDKit canon | PubChem cross-id) -> validate
      -> dedup (InChIKey + fuzzy, 5 levels) -> conflicts (as metadata) -> CSV + report.

Usage:
  python -m hw_chemdb.pipeline --pdf-dir DIR [--out chem_db.csv]
         [--no-molscribe] [--no-enrich] [--all-figures]

Writes: <out> (every annotated record), <out>.dedup.csv (primary rows only),
        processing_report.md (slide-32 report).
"""
from __future__ import annotations
import argparse
import csv
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                              # /root/scinex (so ocr/, domains/, enrich/ import)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hw_chemdb.record import COLUMNS                      # noqa: E402
from hw_chemdb import standardize, dedup, conflicts       # noqa: E402
from hw_chemdb.resolve import Resolver                    # noqa: E402
from hw_chemdb.report import build_report                 # noqa: E402


def extract_one(pdf_path: str, fig_root: str, *, use_molscribe: bool,
                use_decimer: bool, all_figures: bool, skip_figures: bool = False):
    """One PDF -> list[Record] from text + tables + figures (extraction stage only)."""
    from ocr.pdf_extract import extract_pdf
    from hw_chemdb.extract_text import extract_text
    from hw_chemdb.extract_tables import extract_tables
    from hw_chemdb.extract_figures import extract_figures
    name = os.path.basename(pdf_path)
    fig_dir = os.path.join(fig_root, os.path.splitext(name)[0])
    try:
        ex = extract_pdf(pdf_path, fig_dir=fig_dir)
    except Exception as e:                                # a broken PDF must not sink the batch
        sys.stderr.write("[warn] extract failed %s: %s\n" % (name, e))
        return []
    recs = []
    recs += extract_text(ex.get("text", ""), name)
    recs += extract_tables(ex.get("tables", []), name)
    if not skip_figures:                                 # OpenChemIE handles figures when enabled
        recs += extract_figures(ex.get("figures", []), name, use_molscribe=use_molscribe,
                                use_decimer=use_decimer, gate=not all_figures)
    return recs


def build_db(pdf_dir: str, out_csv: str, *, use_molscribe=True, use_decimer=True,
             enrich=True, all_figures=False, use_openchemie=True, do_reactions=False,
             use_schemes=False, fig_root=None, verbose=True):
    pdfs = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")) + glob.glob(os.path.join(pdf_dir, "*.PDF")))
    if not pdfs:
        raise SystemExit("no PDFs in %s" % pdf_dir)
    fig_root = fig_root or os.path.join(os.path.dirname(out_csv) or ".", "_figures")
    records = []
    for i, pdf in enumerate(pdfs, 1):
        if verbose:
            print("[%d/%d] %s" % (i, len(pdfs), os.path.basename(pdf)), flush=True)
        records += extract_one(pdf, fig_root, use_molscribe=use_molscribe,
                               use_decimer=use_decimer, all_figures=all_figures,
                               skip_figures=use_openchemie)
    if verbose:
        print("extracted %d raw records" % len(records), flush=True)
    if use_openchemie:
        from hw_chemdb.extract_openchemie import run_openchemie, build_records, attach_structures
        if verbose:
            print("running OpenChemIE on %d PDFs (coref%s)..." % (
                len(pdfs), " + ChemRxnExtractor" if do_reactions else ""), flush=True)
        results = run_openchemie(pdfs, do_reactions=do_reactions)
        label_maps = {}
        for pdf in pdfs:
            recs, lmap = build_records(pdf, results.get(pdf, {}))
            records += recs
            if lmap:
                label_maps[os.path.basename(pdf)] = lmap
        n_filled = attach_structures(records, label_maps)
        if verbose:
            n_fig = sum(1 for r in records if r.extractor.startswith("openchemie:coref")
                        or r.extractor.startswith("openchemie:moldet"))
            n_yld = sum(1 for r in records if r.extractor.startswith("openchemie:chemrxn"))
            print("  openchemie: +%d figure structures, +%d yield events, %d rows label-matched" % (
                n_fig, n_yld, n_filled), flush=True)
    elif use_schemes:
        from hw_chemdb.extract_schemes import build_schemes, attach_scheme_structures
        label_maps = {}
        scheme_root = os.path.join(os.path.dirname(out_csv) or ".", "_schemes")
        for i, pdf in enumerate(pdfs, 1):
            if verbose:
                print("  [schemes %d/%d] %s" % (i, len(pdfs), os.path.basename(pdf)), flush=True)
            srecs, lmap = build_schemes(pdf, use_molscribe=use_molscribe, use_decimer=use_decimer,
                                        work_root=os.path.join(scheme_root, os.path.splitext(os.path.basename(pdf))[0]))
            records += srecs
            if lmap:
                label_maps[os.path.basename(pdf)] = lmap
        n_filled = attach_scheme_structures(records, label_maps)
        if verbose:
            print("  schemes: +%d structures, %d rows label-matched" % (
                sum(1 for r in records if r.source_type == "scheme"), n_filled), flush=True)
    if verbose:
        print("standardising...", flush=True)
    for r in records:
        standardize.apply(r)
    if verbose:
        print("resolving identifiers (OPSIN/RDKit/PubChem)...", flush=True)
    resolver = Resolver(enrich=enrich)
    for r in records:
        resolver.resolve(r)
    if verbose:
        print("deduplicating + detecting conflicts...", flush=True)
    dedup.deduplicate(records)
    conflicts.detect_conflicts(records)
    for r in records:
        r.assign_id()
    _write_csv(out_csv, records)
    dedup_csv = out_csv[:-4] + ".dedup.csv" if out_csv.endswith(".csv") else out_csv + ".dedup.csv"
    _write_csv(dedup_csv, [r for r in records if r.is_primary is not False])
    md, stats = build_report(records)
    report_path = os.path.join(os.path.dirname(out_csv) or ".", "processing_report.md")
    with open(report_path, "w") as f:
        f.write(md)
    if verbose:
        print("\n%s" % md)
        print("wrote: %s | %s | %s" % (out_csv, dedup_csv, report_path), flush=True)
    return records, stats


def _write_csv(path: str, records) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r.to_row())


def main():
    ap = argparse.ArgumentParser(description="no-LLM PDF -> chemical database")
    ap.add_argument("--pdf-dir", required=True, help="folder of PDFs")
    ap.add_argument("--out", default="chem_db.csv", help="output CSV path")
    ap.add_argument("--fig-dir", default=None, help="where figure crops are written")
    ap.add_argument("--no-molscribe", action="store_true", help="disable MolScribe OCSR (DECIMER only)")
    ap.add_argument("--no-decimer", action="store_true", help="disable DECIMER OCSR (MolScribe only; use in single-env Colab)")
    ap.add_argument("--no-enrich", action="store_true", help="disable PubChem cross-id enrichment")
    ap.add_argument("--all-figures", action="store_true", help="OCSR every image, not just structural captions")
    ap.add_argument("--schemes", action="store_true", help="[legacy] DECIMER-Segmentation scheme layer (superseded by OpenChemIE)")
    ap.add_argument("--no-openchemie", action="store_true", help="disable the OpenChemIE figure/coref path")
    ap.add_argument("--reactions", action="store_true", help="also run ChemRxnExtractor (prep/yield from text; slow)")
    a = ap.parse_args()
    build_db(a.pdf_dir, a.out, use_molscribe=not a.no_molscribe,
             use_decimer=not a.no_decimer, enrich=not a.no_enrich, all_figures=a.all_figures,
             use_openchemie=not a.no_openchemie, do_reactions=a.reactions,
             use_schemes=a.schemes, fig_root=a.fig_dir)


if __name__ == "__main__":
    main()