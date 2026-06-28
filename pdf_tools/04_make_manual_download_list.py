#!/usr/bin/env python
"""
Create a manual download TODO list from failed/missing PDF reports.

Input priority:
  1. manifests/<domain>_download_report.csv
  2. manifests/<domain>_pdf_validation_report.csv

Output:
  manifests/<domain>_manual_download_list.csv

The CSV contains DOI links and suggested local filenames.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from chemx_config import DOMAINS, normalize_domain, safe_filename


def doi_url(doi: str) -> str:
    doi = str(doi).strip()
    if not doi:
        return ""
    return f"https://doi.org/{doi}"


def make_manual_list(domain: str, manifests_dir: Path, out_dir: Path) -> pd.DataFrame:
    download_report = manifests_dir / f"{domain}_download_report.csv"
    validation_report = manifests_dir / f"{domain}_pdf_validation_report.csv"

    if download_report.exists():
        df = pd.read_csv(download_report)
        todo = df[df["status"].isin(["failed", "skipped"])].copy()
    elif validation_report.exists():
        df = pd.read_csv(validation_report)
        todo = df[df["status"].isin(["missing", "bad"])].copy()
    else:
        raise FileNotFoundError(
            f"No report found for {domain}. Expected {download_report} or {validation_report}"
        )

    if todo.empty:
        result = pd.DataFrame(columns=[
            "domain", "pdf", "doi", "doi_url", "suggested_filename", "notes"
        ])
    else:
        result = pd.DataFrame({
            "domain": domain,
            "pdf": todo.get("pdf", ""),
            "doi": todo.get("doi", ""),
        })
        result["doi_url"] = result["doi"].map(doi_url)
        result["suggested_filename"] = result["pdf"].fillna(result["doi"]).map(safe_filename)
        result["notes"] = (
            "Download only legal OA PDF. Save into "
            f"data/pdfs/pdf_{domain}/ with suggested filename."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{domain}_manual_download_list.csv"
    result.to_csv(out_path, index=False)

    print(f"\n[{domain}] manual list saved: {out_path}")
    print(f"Items: {len(result)}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="all", help="Domain short name or 'all'")
    parser.add_argument("--manifests", default="manifests")
    parser.add_argument("--out", default="manifests")
    args = parser.parse_args()

    domain_arg = normalize_domain(args.domain)
    domains = list(DOMAINS) if domain_arg == "all" else [domain_arg]

    all_rows = []
    for domain in domains:
        try:
            all_rows.append(make_manual_list(domain, Path(args.manifests), Path(args.out)))
        except Exception as exc:
            print(f"[FAILED DOMAIN] {domain}: {exc}")

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
        combined_path = Path(args.out) / "_combined_manual_download_list.csv"
        combined.to_csv(combined_path, index=False)
        print(f"\nCombined manual list saved: {combined_path}")


if __name__ == "__main__":
    main()
