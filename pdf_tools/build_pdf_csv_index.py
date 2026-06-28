#!/usr/bin/env python
"""Build explicit PDF <-> CSV correspondence index and verify round-trip."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from chemx_config import DOMAINS

DS = Path("data/datasets")
PDF_ROOT = Path("data/pdfs")

rows = []
for domain in DOMAINS:
    f = DS / f"{domain}_metrics_matched.csv"
    if not f.exists():
        continue
    try:
        df = pd.read_csv(f)
    except pd.errors.EmptyDataError:
        continue
    if df.empty:
        continue
    for pdf_file, sub in df.groupby("pdf_file"):
        rows.append({
            "domain": domain,
            "pdf": sub["pdf"].iloc[0] if "pdf" in sub.columns else "",
            "doi": sub["doi"].iloc[0] if "doi" in sub.columns else "",
            "pdf_file": pdf_file,
            "pdf_exists": Path(pdf_file).exists(),
            "metrics_csv": str(f),
            "n_metric_rows": len(sub),
        })

idx = pd.DataFrame(rows).sort_values(["domain", "pdf_file"]).reset_index(drop=True)
idx.to_csv(DS / "_pdf_csv_index.csv", index=False)

on_disk = {p.name for p in PDF_ROOT.rglob("*.pdf") if p.stat().st_size > 1000}
idx_names = {Path(p).name for p in idx["pdf_file"]}

print("=== PDF <-> CSV index ===")
print("unique PDFs in index      :", idx["pdf_file"].nunique())
print("all referenced files exist:", bool(idx["pdf_exists"].all()))
print("total metric rows mapped  :", int(idx["n_metric_rows"].sum()))
print("PDF files on disk (>1kb)  :", len(on_disk))
print("on disk but NOT in index  :", len(on_disk - idx_names), sorted(on_disk - idx_names)[:5])
print("in index but NOT on disk  :", len(idx_names - on_disk))
print()
print("per-domain unique PDFs / rows:")
agg = idx.groupby("domain").agg(pdfs=("pdf_file", "nunique"), rows=("n_metric_rows", "sum"))
print(agg.to_string())
print()
print("sample (domain | pdf | n_rows | csv):")
print(idx[["domain", "pdf", "n_metric_rows", "metrics_csv"]].head(6).to_string(index=False))
print(f"\nSaved: {DS}/_pdf_csv_index.csv")