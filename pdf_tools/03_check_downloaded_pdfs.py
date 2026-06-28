#!/usr/bin/env python
"""
Validate downloaded PDF folders.

Checks:
  - file exists for each manifest row
  - file starts with %PDF
  - file size is above threshold
  - creates per-domain and combined validation reports

Examples:
  python 03_check_downloaded_pdfs.py --domain benzimidazole
  python 03_check_downloaded_pdfs.py --domain all
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from chemx_config import DOMAINS, looks_like_pdf_bytes, normalize_domain, safe_filename


def read_manifest(domain: str, manifests_dir: Path) -> pd.DataFrame:
    path = manifests_dir / f"{domain}_open_access_manifest.csv"
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    return pd.read_csv(path)


def validate_file(path: Path, min_bytes: int) -> tuple[str, str, int]:
    if not path.exists():
        return "missing", "file_not_found", 0

    size = path.stat().st_size
    if size < min_bytes:
        return "bad", "too_small", size

    try:
        with path.open("rb") as f:
            head = f.read(8)
    except OSError as exc:
        return "bad", f"read_error:{type(exc).__name__}", size

    if not looks_like_pdf_bytes(head):
        return "bad", "not_pdf_header", size

    return "ok", "", size


def validate_domain(
    domain: str,
    manifests_dir: Path,
    pdf_root: Path,
    reports_dir: Path,
    min_bytes: int,
) -> pd.DataFrame:
    manifest = read_manifest(domain, manifests_dir)
    pdf_dir = pdf_root / f"pdf_{domain}"

    rows = []
    for _, row in manifest.iterrows():
        doi = str(row.get("doi", "")).strip()
        pdf_id = str(row.get("pdf", "")).strip() if pd.notna(row.get("pdf", "")) else doi
        filename = safe_filename(pdf_id or doi)
        path = pdf_dir / filename

        status, reason, size = validate_file(path, min_bytes)

        rows.append({
            "domain": domain,
            "pdf": pdf_id,
            "doi": doi,
            "status": status,
            "reason": reason,
            "size_bytes": size,
            "path": str(path),
        })

    report = pd.DataFrame(rows)
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"{domain}_pdf_validation_report.csv"
    report.to_csv(out_path, index=False)

    print(f"\n[{domain}] validation saved: {out_path}")
    print(report["status"].value_counts(dropna=False).to_string())

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="all", help="Domain short name or 'all'")
    parser.add_argument("--manifests", default="manifests")
    parser.add_argument("--pdf-root", default="data/pdfs")
    parser.add_argument("--reports", default="manifests")
    parser.add_argument("--min-bytes", type=int, default=1000)
    args = parser.parse_args()

    domain_arg = normalize_domain(args.domain)
    domains = list(DOMAINS) if domain_arg == "all" else [domain_arg]

    reports = []
    for domain in domains:
        try:
            reports.append(validate_domain(
                domain=domain,
                manifests_dir=Path(args.manifests),
                pdf_root=Path(args.pdf_root),
                reports_dir=Path(args.reports),
                min_bytes=args.min_bytes,
            ))
        except Exception as exc:
            print(f"[FAILED DOMAIN] {domain}: {exc}")

    if reports:
        combined = pd.concat(reports, ignore_index=True)
        combined_path = Path(args.reports) / "_combined_pdf_validation_report.csv"
        combined.to_csv(combined_path, index=False)
        print(f"\nCombined validation report saved: {combined_path}")


if __name__ == "__main__":
    main()
