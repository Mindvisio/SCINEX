#!/usr/bin/env python
"""
Export ChemX ground-truth measurement tables keyed to downloaded PDFs.

Join key: dataset column `pdf` -> local file safe_filename(pdf) in data/pdfs/pdf_<domain>/.
Outputs (data/datasets/):
  <domain>_metrics.csv          full ground-truth + pdf_file + pdf_downloaded flag
  <domain>_metrics_matched.csv  only rows whose PDF is present on disk
  _metrics_coverage.csv         per-domain coverage summary
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import datasets

datasets.disable_progress_bars()

from chemx_config import DOMAINS, safe_filename

OUT = Path("data/datasets")
OUT.mkdir(parents=True, exist_ok=True)
PDF_ROOT = Path("data/pdfs")


def expected_filename(row: pd.Series) -> str:
    pdf_val = row.get("pdf")
    doi = str(row.get("doi", "")).strip()
    pdf_id = str(pdf_val).strip() if pd.notna(pdf_val) else doi
    return safe_filename(pdf_id or doi)


summary = []
for domain, hf in DOMAINS.items():
    df = datasets.load_dataset(f"ai-chem/{hf}")["train"].to_pandas().copy()
    pdf_dir = PDF_ROOT / f"pdf_{domain}"
    present = {p.name for p in pdf_dir.glob("*.pdf")} if pdf_dir.exists() else set()

    fnames = df.apply(expected_filename, axis=1)
    df["pdf_file"] = [str(pdf_dir / f) for f in fnames]
    df["pdf_downloaded"] = [f in present for f in fnames]

    df.to_csv(OUT / f"{domain}_metrics.csv", index=False)
    matched = df[df["pdf_downloaded"]]
    matched.to_csv(OUT / f"{domain}_metrics_matched.csv", index=False)

    has_pdf_col = "pdf" in df.columns
    summary.append({
        "domain": domain,
        "hf_dataset": hf,
        "rows_total": len(df),
        "unique_pdf": df["pdf"].nunique() if has_pdf_col else None,
        "rows_matched": int(df["pdf_downloaded"].sum()),
        "unique_pdf_matched": matched["pdf"].nunique() if has_pdf_col else None,
        "pdf_files_on_disk": len(present),
    })
    print(f"{domain:14s} rows={len(df):5d} matched_rows={int(df['pdf_downloaded'].sum()):5d} "
          f"uniq_pdf_matched={matched['pdf'].nunique() if has_pdf_col else 0:3d} "
          f"pdf_on_disk={len(present):3d}")

sdf = pd.DataFrame(summary)
sdf.to_csv(OUT / "_metrics_coverage.csv", index=False)
print("\n=== coverage ===")
print(sdf.to_string(index=False))
print(f"\nSaved to {OUT}/")