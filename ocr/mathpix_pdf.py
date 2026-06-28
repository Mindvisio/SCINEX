#!/usr/bin/env python3
"""Mathpix PDF обработка: загрузка → polling → скачивание md + tex.zip + bibliography update.

CLI:
    python3 scripts/tools/mathpix_pdf.py PATH_TO.pdf [--bib KEY] [--stem STEM] [--force]

--bib KEY
    BibTeX-ключ в data/bibliography.json. Если указан, скрипт:
      — берёт project_stem из записи в bibliography для имен выходных файлов
      — после обработки обновляет local_files и mathpix_status в записи

--stem STEM
    Явный stem для выходных файлов (переопределяет поиск через --bib)

Без --bib и --stem stem = pdf basename без расширения.

Outputs into data/literature/:
    <stem>.mathpix.md
    <stem>.mathpix.tex.zip
    <stem>.mathpix.tex   (extracted standalone TeX)
    <stem>.mathpix.meta.json   (pdf_id, sha256, page count, durations, bib_key)

Idempotent: if outputs exist and source PDF sha256 matches meta, skips re-upload
(but всё равно обновляет bibliography если --bib).

Keys are read from /root/.api_keys (MATHPIX_APP_ID, MATHPIX_APP_KEY).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("requests не установлен. в venv: pip install requests")

API_BASE = "https://api.mathpix.com/v3"
KEYS_FILE = Path(os.environ.get("SCINEX_KEYS_FILE") or (Path.cwd()/".env" if (Path.cwd()/".env").exists() else (Path.home()/".api_keys" if (Path.home()/".api_keys").exists() else "/root/.api_keys")))
BIBLIOGRAPHY = Path(os.environ.get("SCINEX_BIBLIOGRAPHY", str(Path(__file__).resolve().parent.parent/"data"/"bibliography.json")))
DEFAULT_OPTIONS = {
    "conversion_formats": {"md": True, "tex.zip": True},
    "math_inline_delimiters": ["$", "$"],
    "math_display_delimiters": ["$$", "$$"],
    "rm_spaces": True,
    "enable_tables_fallback": True,
    "include_line_data": True,   # per-line bbox(cnt/region)+type+confidence+confidence_rate -> lines.json
}


def _read_keys() -> tuple[str, str]:
    if not KEYS_FILE.exists():
        sys.exit(f"нет {KEYS_FILE}")
    app_id = app_key = None
    for line in KEYS_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("MATHPIX_APP_ID="):
            app_id = line.split("=", 1)[1].strip().strip("'\"")
        elif line.startswith("MATHPIX_APP_KEY="):
            app_key = line.split("=", 1)[1].strip().strip("'\"")
    if not app_id or not app_key:
        sys.exit("MATHPIX_APP_ID / MATHPIX_APP_KEY не найдены в ~/.api_keys")
    return app_id, app_key


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 16), b""):
            h.update(ch)
    return h.hexdigest()


@dataclass
class Meta:
    pdf_id: str
    source_pdf: str
    source_sha256: str
    num_pages: int
    duration_seconds: float
    formats: list[str]
    bib_key: Optional[str] = None
    api_version: str = "v3"


def submit_pdf(path: Path, app_id: str, app_key: str, options: Optional[dict] = None) -> str:
    opts = json.dumps(options or DEFAULT_OPTIONS)
    with open(path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/pdf",
            headers={"app_id": app_id, "app_key": app_key},
            files={"file": (path.name, f, "application/pdf")},
            data={"options_json": opts},
            timeout=120,
        )
    r.raise_for_status()
    body = r.json()
    if "pdf_id" not in body:
        sys.exit(f"submit failed: {body}")
    return body["pdf_id"]


def poll(pdf_id: str, app_id: str, app_key: str, *, max_wait: int = 1800, interval: int = 5,
        verbose: bool = True) -> dict:
    headers = {"app_id": app_id, "app_key": app_key}
    started = time.time()
    last_pct = -1
    while True:
        elapsed = time.time() - started
        if elapsed > max_wait:
            sys.exit(f"timeout {max_wait}s waiting for {pdf_id}")
        r = requests.get(f"{API_BASE}/pdf/{pdf_id}", headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        status = body.get("status", "unknown")
        pct = body.get("percent_done", 0)
        if verbose and pct != last_pct:
            print(f"  [{int(elapsed)}s] {status} {pct}%", flush=True)
            last_pct = pct
        if status == "completed":
            return body
        if status == "error":
            sys.exit(f"error: {body}")
        time.sleep(interval)


def download_format(pdf_id: str, fmt: str, dest: Path, app_id: str, app_key: str) -> int:
    url = f"{API_BASE}/pdf/{pdf_id}.{fmt}"
    r = requests.get(url, headers={"app_id": app_id, "app_key": app_key}, timeout=120)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "json" in ctype and fmt != "lines.json":
        sys.exit(f"download error {fmt}: {r.text}")
    dest.write_bytes(r.content)
    return len(r.content)


def extract_tex(zip_path: Path, dest_tex: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        tex_names = [n for n in zf.namelist() if n.endswith(".tex")]
        if not tex_names:
            print(f"  [warn] no .tex inside {zip_path}")
            return
        with zf.open(tex_names[0]) as src:
            dest_tex.write_bytes(src.read())


def _load_bib() -> dict:
    if not BIBLIOGRAPHY.exists():
        sys.exit(f"bibliography missing: {BIBLIOGRAPHY}")
    return json.loads(BIBLIOGRAPHY.read_text(encoding="utf-8"))


def _save_bib(bib: dict) -> None:
    BIBLIOGRAPHY.write_text(json.dumps(bib, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_stem(bib_key: Optional[str], stem_arg: Optional[str], pdf_path: Path) -> tuple[str, Optional[dict]]:
    """Returns (stem, bib_entry).
    
    Priority: --stem > bib.project_stem > pdf.stem.
    bib_entry returned if --bib provided and resolved.
    """
    if stem_arg:
        stem = stem_arg
    elif bib_key:
        bib = _load_bib()
        entry = next((e for e in bib["entries"] if e["key"] == bib_key), None)
        if not entry:
            sys.exit(f"bib_key '{bib_key}' не найден в {BIBLIOGRAPHY}")
        stem = entry.get("project_stem") or pdf_path.stem
        return stem, entry
    else:
        stem = pdf_path.stem
    return stem, None


def _update_bib_entry(bib_key: str, stem: str, src_sha: str) -> None:
    bib = _load_bib()
    LIT_REL = "data/literature"
    for e in bib["entries"]:
        if e["key"] == bib_key:
            e["local_files"] = {
                "pdf": f"{LIT_REL}/{stem}.pdf",
                "pdf_sha12": src_sha[:12],
                "mathpix_md": f"{LIT_REL}/{stem}.mathpix.md",
                "mathpix_tex": f"{LIT_REL}/{stem}.mathpix.tex",
            }
            e["mathpix_status"] = "processed"
            if not e.get("project_stem"):
                e["project_stem"] = stem
            from datetime import datetime, timezone
            bib["updated"] = datetime.now(timezone.utc).isoformat()
            _save_bib(bib)
            return
    sys.exit(f"bib_key '{bib_key}' не найден при update")


def process_pdf(pdf_path: Path, *, bib_key: Optional[str] = None, stem: Optional[str] = None,
                force: bool = False, verbose: bool = True) -> Meta:
    if not pdf_path.exists():
        sys.exit(f"нет PDF: {pdf_path}")

    app_id, app_key = _read_keys()
    resolved_stem, _ = _resolve_stem(bib_key, stem, pdf_path)

    base_dir = pdf_path.parent
    md_out = base_dir / f"{resolved_stem}.mathpix.md"
    zip_out = base_dir / f"{resolved_stem}.mathpix.tex.zip"
    tex_out = base_dir / f"{resolved_stem}.mathpix.tex"
    meta_out = base_dir / f"{resolved_stem}.mathpix.meta.json"

    src_sha = _sha256(pdf_path)

    # idempotency check (skip API call but still update bibliography)
    if not force and meta_out.exists() and md_out.exists():
        try:
            existing = json.loads(meta_out.read_text())
            if existing.get("source_sha256") == src_sha:
                if verbose:
                    print(f"[skip] {pdf_path.name}: already processed (pdf_id={existing.get('pdf_id')})")
                if bib_key:
                    _update_bib_entry(bib_key, resolved_stem, src_sha)
                    if verbose:
                        print(f"[bib] updated entry {bib_key} (cached run)")
                return Meta(**{**existing, "bib_key": bib_key})
        except Exception:
            pass

    if verbose:
        print(f"[submit] {pdf_path.name} ({pdf_path.stat().st_size:,} bytes)")
        if bib_key:
            print(f"  bib_key = {bib_key}, stem = {resolved_stem}")
    started = time.time()
    pdf_id = submit_pdf(pdf_path, app_id, app_key)
    if verbose:
        print(f"  pdf_id = {pdf_id}")
    body = poll(pdf_id, app_id, app_key, verbose=verbose)
    duration = time.time() - started
    pages = body.get("num_pages", 0)
    if verbose:
        print(f"[ok] {pages} pages in {duration:.1f}s, downloading...")

    md_size = download_format(pdf_id, "md", md_out, app_id, app_key)
    zip_size = download_format(pdf_id, "tex.zip", zip_out, app_id, app_key)
    extract_tex(zip_out, tex_out)

    if verbose:
        print(f"  md     : {md_out.name} ({md_size:,} bytes)")
        print(f"  tex.zip: {zip_out.name} ({zip_size:,} bytes)")
        print(f"  tex    : {tex_out.name} ({tex_out.stat().st_size:,} bytes)")

    meta = Meta(
        pdf_id=pdf_id,
        source_pdf=str(pdf_path.relative_to(Path('/root/strange_lie')))
            if str(pdf_path).startswith("/root/strange_lie/") else str(pdf_path),
        source_sha256=src_sha,
        num_pages=pages,
        duration_seconds=round(duration, 1),
        formats=["md", "tex.zip", "tex"],
        bib_key=bib_key,
    )
    meta_out.write_text(json.dumps(asdict(meta), indent=2, ensure_ascii=False) + "\n")

    if bib_key:
        _update_bib_entry(bib_key, resolved_stem, src_sha)
        if verbose:
            print(f"[bib] updated entry {bib_key} → mathpix_status=processed")

    return meta


def main():
    ap = argparse.ArgumentParser(description="Mathpix PDF → markdown + tex (+ bibliography update)")
    ap.add_argument("pdf", type=Path, help="path to PDF")
    ap.add_argument("--bib", help="BibTeX key in data/bibliography.json (auto-updates entry on success)")
    ap.add_argument("--stem", help="override output stem (default: bib.project_stem or pdf basename)")
    ap.add_argument("--force", action="store_true", help="reprocess even if cached")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    meta = process_pdf(args.pdf, bib_key=args.bib, stem=args.stem,
                       force=args.force, verbose=not args.quiet)
    if not args.quiet:
        print(f"\n[done] {meta.num_pages} pages in {meta.duration_seconds}s")


if __name__ == "__main__":
    main()