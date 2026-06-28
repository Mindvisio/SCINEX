#!/usr/bin/env python
"""
Download open-access ChemX PDFs from DOI manifests.

Pipeline:
  ChemX HF manifest -> DOI -> Unpaywall -> direct OA PDF -> data/pdfs/pdf_<domain>/<pdf>.pdf

Examples:
  python 01_make_chemx_oa_manifests.py --domain benzimidazole
  python 02_download_chemx_pdfs.py --domain benzimidazole --email you@example.com

  python 01_make_chemx_oa_manifests.py --domain all
  python 02_download_chemx_pdfs.py --domain all --email you@example.com

Notes:
  - Does not bypass paywalls.
  - Only downloads direct PDF responses discovered from OA metadata.
  - Some failed DOI records will need manual download from publisher/PMC/SciELO/etc.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from tqdm import tqdm

from chemx_config import (
    DOMAINS,
    ensure_dir,
    looks_like_pdf_response,
    normalize_domain,
    pdf_output_dir,
    safe_filename,
)


def read_manifest(domain: str, manifests_dir: Path) -> pd.DataFrame:
    path = manifests_dir / f"{domain}_open_access_manifest.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Manifest not found: {path}\n"
            f"Run: python 01_make_chemx_oa_manifests.py --domain {domain}"
        )
    df = pd.read_csv(path)
    if "doi" not in df.columns:
        raise ValueError(f"Manifest has no doi column: {path}")
    return df


def get_unpaywall_urls(doi: str, email: str, session: requests.Session) -> list[str]:
    """
    Return candidate OA URLs from Unpaywall.
    Try url_for_pdf first, then landing page URL.
    """
    url = f"https://api.unpaywall.org/v2/{quote(doi)}?email={quote(email)}"

    try:
        r = session.get(url, timeout=30)
    except requests.RequestException:
        return []

    if r.status_code != 200:
        return []

    try:
        data = r.json()
    except ValueError:
        return []

    locations = []
    best = data.get("best_oa_location")
    if best:
        locations.append(best)

    for loc in data.get("oa_locations") or []:
        if isinstance(loc, dict):
            locations.append(loc)

    urls: list[str] = []
    seen = set()

    for loc in locations:
        for key in ("url_for_pdf", "url"):
            u = loc.get(key)
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

    return urls


def try_download_pdf(url: str, session: requests.Session, out_path: Path) -> tuple[bool, str]:
    """
    Download only if response looks like a real PDF.
    Returns (ok, reason).
    """
    try:
        r = session.get(url, timeout=60, allow_redirects=True)
    except requests.RequestException as exc:
        return False, f"request_error:{type(exc).__name__}"

    if r.status_code != 200:
        return False, f"http_{r.status_code}"

    if not looks_like_pdf_response(r):
        ctype = r.headers.get("content-type", "")
        return False, f"not_pdf:{ctype}"

    if len(r.content) < 1000:
        return False, "too_small"

    out_path.write_bytes(r.content)
    return True, "downloaded"


def download_domain(
    domain: str,
    email: str,
    manifests_dir: Path,
    pdf_root: Path,
    reports_dir: Path,
    sleep: float,
    overwrite: bool,
) -> pd.DataFrame:
    manifest = read_manifest(domain, manifests_dir)
    out_dir = pdf_output_dir(pdf_root, domain)

    session = requests.Session()
    session.headers.update({
        "User-Agent": f"ChemX-OA-PDF-Downloader/0.1 mailto:{email}"
    })

    rows = []

    for _, row in tqdm(manifest.iterrows(), total=len(manifest), desc=domain):
        doi = str(row.get("doi", "")).strip()
        pdf_id = str(row.get("pdf", "")).strip() if pd.notna(row.get("pdf", "")) else doi

        if not doi:
            rows.append({
                "domain": domain,
                "pdf": pdf_id,
                "doi": doi,
                "status": "skipped",
                "reason": "empty_doi",
                "saved_path": "",
                "source_url": "",
            })
            continue

        filename = safe_filename(pdf_id or doi)
        out_path = out_dir / filename

        if out_path.exists() and out_path.stat().st_size > 1000 and not overwrite:
            rows.append({
                "domain": domain,
                "pdf": pdf_id,
                "doi": doi,
                "status": "exists",
                "reason": "",
                "saved_path": str(out_path),
                "source_url": "",
            })
            continue

        urls = get_unpaywall_urls(doi, email, session)

        ok = False
        used_url = ""
        last_reason = "no_oa_url"

        for u in urls:
            ok, reason = try_download_pdf(u, session, out_path)
            last_reason = reason
            if ok:
                used_url = u
                break

        rows.append({
            "domain": domain,
            "pdf": pdf_id,
            "doi": doi,
            "status": "downloaded" if ok else "failed",
            "reason": last_reason,
            "saved_path": str(out_path) if ok else "",
            "source_url": used_url,
        })

        time.sleep(sleep)

    report = pd.DataFrame(rows)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{domain}_download_report.csv"
    report.to_csv(report_path, index=False)

    print(f"\n[{domain}] saved report: {report_path}")
    print(report["status"].value_counts(dropna=False).to_string())

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, help="Domain short name or 'all'")
    parser.add_argument("--email", required=True, help="Email required by Unpaywall API")
    parser.add_argument("--manifests", default="manifests", help="Manifest folder")
    parser.add_argument("--out", default="data/pdfs", help="PDF output root")
    parser.add_argument("--reports", default="manifests", help="Report output folder")
    parser.add_argument("--sleep", type=float, default=1.0, help="Delay between DOI requests")
    parser.add_argument("--overwrite", action="store_true", help="Redownload existing PDFs")
    args = parser.parse_args()

    domain_arg = normalize_domain(args.domain)
    domains = list(DOMAINS) if domain_arg == "all" else [domain_arg]

    all_reports = []
    for domain in domains:
        try:
            report = download_domain(
                domain=domain,
                email=args.email,
                manifests_dir=Path(args.manifests),
                pdf_root=Path(args.out),
                reports_dir=ensure_dir(args.reports),
                sleep=args.sleep,
                overwrite=args.overwrite,
            )
            all_reports.append(report)
        except Exception as exc:
            print(f"[FAILED DOMAIN] {domain}: {exc}")

    if all_reports:
        combined = pd.concat(all_reports, ignore_index=True)
        combined_path = Path(args.reports) / "_combined_download_report.csv"
        combined.to_csv(combined_path, index=False)
        print(f"\nCombined report saved: {combined_path}")


if __name__ == "__main__":
    main()
