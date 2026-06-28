"""
Shared config and utilities for ChemX PDF manifest/download scripts.

Supported domains use short names compatible with ChemX/LLM folder naming:
  data/pdfs/pdf_<domain>
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


DOMAINS: dict[str, str] = {
    "eyedrops": "EyeDrops",
    "benzimidazole": "Benzimidazoles",
    "oxazolidinone": "Oxazolidinones",
    "nanozymes": "Nanozymes",
    "synergy": "Synergy",
    "nanomag": "Nanomag",
    "cocrystals": "Co-crystals",
    "complexes": "Complexes",
    "cytotox": "Cytotox",
    "seltox": "SelTox",
}


def normalize_domain(domain: str) -> str:
    """Normalize user-provided domain aliases to internal short names."""
    d = domain.strip().lower().replace("_", "-")

    aliases = {
        "benzymidazole": "benzimidazole",
        "benzimidazoles": "benzimidazole",
        "oxazolidinones": "oxazolidinone",
        "nanozyme": "nanozymes",
        "co-crystals": "cocrystals",
        "cocrystal": "cocrystals",
        "cocrystals": "cocrystals",
        "complex": "complexes",
        "magnetic": "nanomag",
        "nanomagnetic": "nanomag",
        "cytotoxicity": "cytotox",
        "sel-tox": "seltox",
        "eye-drops": "eyedrops",
        "eye_drops": "eyedrops",
    }

    d = aliases.get(d, d)

    if d not in DOMAINS and d != "all":
        allowed = ", ".join(sorted(list(DOMAINS) + ["all"]))
        raise ValueError(f"Unknown domain '{domain}'. Allowed: {allowed}")

    return d


def is_open_access(value: Any) -> bool:
    """
    Interpret ChemX OA flags robustly.
    ChemX usually uses access == 1, but some datasets may also contain is_oa/oa_status.
    """
    if value is None:
        return False

    try:
        import pandas as pd  # local import to avoid hard dependency at import time
        if pd.isna(value):
            return False
    except Exception:
        pass

    s = str(value).strip().lower()
    return s in {
        "1",
        "1.0",
        "true",
        "yes",
        "y",
        "open",
        "oa",
        "gold",
        "green",
        "hybrid",
        "bronze",
    }


def safe_filename(value: str, suffix: str = ".pdf", max_len: int = 180) -> str:
    """
    Turn ChemX pdf id / DOI / title into a filesystem-safe filename.

    Important: for ChemX evaluation, keep the `pdf` id in pred.csv exactly as in HF.
    The filename can be `<pdf>.pdf`, but the CSV `pdf` value should not include extra changes.
    """
    value = str(value).strip()
    value = re.sub(r"[\\/:\*\?\"<>\|\n\r\t]+", "_", value)
    value = re.sub(r"\s+", "_", value)
    value = value.strip("._ ")
    value = value[:max_len] or "unknown"

    if suffix and not value.lower().endswith(suffix.lower()):
        value += suffix

    return value


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def pdf_output_dir(root: str | Path, domain: str) -> Path:
    """Return ChemX-compatible PDF folder: root/pdf_<domain>."""
    domain = normalize_domain(domain)
    return ensure_dir(Path(root) / f"pdf_{domain}")


def looks_like_pdf_bytes(content: bytes) -> bool:
    return content[:4] == b"%PDF"


def looks_like_pdf_response(resp: Any) -> bool:
    ctype = resp.headers.get("content-type", "").lower()
    return looks_like_pdf_bytes(resp.content) or "application/pdf" in ctype or "pdf" in ctype
