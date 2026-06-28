#!/usr/bin/env python
"""
Create open-access manifest CSV files for ChemX domains.

Example:
  python 01_make_chemx_oa_manifests.py --domain benzimidazole
  python 01_make_chemx_oa_manifests.py --domain all

Output:
  manifests/<domain>_open_access_manifest.csv
  manifests/_summary_open_access.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from datasets import load_dataset

from chemx_config import DOMAINS, is_open_access, normalize_domain, ensure_dir


PREFERRED_COLUMNS = [
    "pdf",
    "doi",
    "title",
    "journal",
    "journal_name",
    "publisher",
    "year",
    "access",
    "is_oa",
    "oa_status",
    "reference",
]


def load_chemx_dataset(hf_name: str) -> pd.DataFrame:
    ds = load_dataset(f"ai-chem/{hf_name}")["train"]
    return ds.to_pandas()


def select_open_access(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prefer ChemX access == 1 if available.
    Fallback to is_oa/oa_status when access column is absent.
    """
    if "access" in df.columns:
        return df[df["access"].map(is_open_access)].copy()

    if "is_oa" in df.columns:
        return df[df["is_oa"].map(is_open_access)].copy()

    if "oa_status" in df.columns:
        return df[df["oa_status"].map(is_open_access)].copy()

    raise ValueError("No access/is_oa/oa_status column found")


def make_manifest(domain: str, out_dir: Path) -> dict:
    hf_name = DOMAINS[domain]
    df = load_chemx_dataset(hf_name)
    oa = select_open_access(df)

    cols = [c for c in PREFERRED_COLUMNS if c in oa.columns]
    manifest = oa[cols].copy() if cols else oa.copy()

    dedup_cols = [c for c in ["pdf", "doi"] if c in manifest.columns]
    if dedup_cols:
        manifest = manifest.drop_duplicates(subset=dedup_cols)
    else:
        manifest = manifest.drop_duplicates()

    if "doi" in manifest.columns:
        manifest["doi"] = manifest["doi"].astype(str).str.strip()
        manifest = manifest[manifest["doi"].notna()]
        manifest = manifest[manifest["doi"].str.len() > 0]
        manifest = manifest.sort_values("doi", na_position="last")

    out_path = out_dir / f"{domain}_open_access_manifest.csv"
    manifest.to_csv(out_path, index=False)

    return {
        "domain": domain,
        "hf_dataset": hf_name,
        "rows_total": len(df),
        "oa_rows": len(oa),
        "unique_oa_pdf": oa["pdf"].nunique() if "pdf" in oa.columns else None,
        "unique_oa_doi": oa["doi"].nunique() if "doi" in oa.columns else None,
        "manifest_rows": len(manifest),
        "manifest_path": str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="all", help="Domain short name or 'all'")
    parser.add_argument("--out", default="manifests", help="Output folder for manifests")
    args = parser.parse_args()

    domain_arg = normalize_domain(args.domain)
    out_dir = ensure_dir(args.out)

    domains = list(DOMAINS) if domain_arg == "all" else [domain_arg]

    summary = []
    for domain in domains:
        print(f"\n=== {domain} ===")
        try:
            row = make_manifest(domain, out_dir)
            summary.append(row)

            print(f"HF dataset:       {row['hf_dataset']}")
            print(f"Rows total:       {row['rows_total']}")
            print(f"OA rows:          {row['oa_rows']}")
            print(f"Unique OA PDFs:   {row['unique_oa_pdf']}")
            print(f"Unique OA DOIs:   {row['unique_oa_doi']}")
            print(f"Manifest rows:    {row['manifest_rows']}")
            print(f"Saved:            {row['manifest_path']}")
        except Exception as exc:
            print(f"FAILED {domain}: {exc}")
            summary.append({
                "domain": domain,
                "hf_dataset": DOMAINS.get(domain),
                "error": str(exc),
            })

    summary_df = pd.DataFrame(summary)
    summary_path = out_dir / "_summary_open_access.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"\nSummary saved: {summary_path}")


if __name__ == "__main__":
    main()
