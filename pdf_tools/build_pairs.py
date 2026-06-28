#!/usr/bin/env python
"""Build literal 1:1 PDF<->CSV pairs: data/pairs/<domain>/<stem>.pdf + <stem>.csv"""
from __future__ import annotations
from pathlib import Path
import os
import shutil
import pandas as pd
from chemx_config import DOMAINS

DS = Path("data/datasets")
PAIRS = Path("data/pairs")
HELPER_COLS = ["pdf_file", "pdf_downloaded"]

index = []
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
    outdir = PAIRS / domain
    outdir.mkdir(parents=True, exist_ok=True)
    for pdf_file, sub in df.groupby("pdf_file"):
        src = Path(pdf_file)
        if not src.exists():
            continue
        stem = src.stem
        dst_pdf = outdir / f"{stem}.pdf"
        dst_csv = outdir / f"{stem}.csv"
        if not dst_pdf.exists():
            try:
                os.link(src, dst_pdf)          # hardlink, 0 extra bytes
            except OSError:
                shutil.copy2(src, dst_pdf)      # fallback cross-fs
        clean = sub.drop(columns=[c for c in HELPER_COLS if c in sub.columns])
        clean.to_csv(dst_csv, index=False)
        index.append({
            "domain": domain,
            "stem": stem,
            "pdf": sub["pdf"].iloc[0] if "pdf" in sub.columns else "",
            "doi": sub["doi"].iloc[0] if "doi" in sub.columns else "",
            "n_rows": len(clean),
            "pdf_path": str(dst_pdf),
            "csv_path": str(dst_csv),
        })

idx = pd.DataFrame(index).sort_values(["domain", "stem"]).reset_index(drop=True)
idx.to_csv(PAIRS / "_pairs_index.csv", index=False)

# verify
n_pdf = sum(1 for _ in PAIRS.rglob("*.pdf"))
n_csv = sum(1 for _ in PAIRS.rglob("*.csv")) - 1  # minus _pairs_index.csv
bad = [r for r in index if not Path(r["csv_path"]).exists() or not Path(r["pdf_path"]).exists()]
print("=== pairs built ===")
print("pair rows in index :", len(idx))
print(".pdf files in pairs :", n_pdf)
print(".csv sidecars       :", n_csv)
print("rows mapped total   :", int(idx["n_rows"].sum()))
print("broken pairs        :", len(bad))
print()
print(idx.groupby("domain").agg(pairs=("stem", "count"), rows=("n_rows", "sum")).to_string())
print(f"\nSaved tree under {PAIRS}/  + {PAIRS}/_pairs_index.csv")