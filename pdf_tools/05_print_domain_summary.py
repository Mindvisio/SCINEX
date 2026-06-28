#!/usr/bin/env python
"""
Print compact summary across manifests/download/validation reports.

Example:
  python 05_print_domain_summary.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from chemx_config import DOMAINS


def count_status(path: Path, status_col: str = "status") -> dict:
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return {}
    if status_col not in df.columns:
        return {}
    return df[status_col].value_counts(dropna=False).to_dict()


def main() -> None:
    manifests = Path("manifests")
    rows = []

    for domain in DOMAINS:
        manifest_path = manifests / f"{domain}_open_access_manifest.csv"
        download_path = manifests / f"{domain}_download_report.csv"
        validation_path = manifests / f"{domain}_pdf_validation_report.csv"

        manifest_rows = None
        unique_doi = None
        unique_pdf = None

        if manifest_path.exists():
            mf = pd.read_csv(manifest_path)
            manifest_rows = len(mf)
            unique_doi = mf["doi"].nunique() if "doi" in mf.columns else None
            unique_pdf = mf["pdf"].nunique() if "pdf" in mf.columns else None

        dl = count_status(download_path)
        val = count_status(validation_path)

        rows.append({
            "domain": domain,
            "manifest_rows": manifest_rows,
            "unique_doi": unique_doi,
            "unique_pdf": unique_pdf,
            "downloaded": dl.get("downloaded", 0),
            "exists": dl.get("exists", 0),
            "download_failed": dl.get("failed", 0),
            "valid_ok": val.get("ok", 0),
            "valid_missing": val.get("missing", 0),
            "valid_bad": val.get("bad", 0),
        })

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    out = manifests / "_compact_summary.csv"
    manifests.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()