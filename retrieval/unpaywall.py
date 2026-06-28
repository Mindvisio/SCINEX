"""Unpaywall — DOI -> open-access PDF URL. NOT a search source; this is the ACCESS layer
that feeds PDFs to ocr/mathpix for full-text extraction. Free; requires an email.
"""
import logging
from typing import Optional

import httpx

from config import env

logger = logging.getLogger(__name__)
BASE = "https://api.unpaywall.org/v2"


def resolve_oa_pdf(doi: str, *, email: Optional[str] = None, timeout: float = 20.0) -> Optional[str]:
    """Return best open-access PDF (or landing) URL for a DOI, or None."""
    email = email or env("UNPAYWALL_EMAIL") or env("CONTACT_EMAIL") or "demo@example.com"
    try:
        r = httpx.get(f"{BASE}/{doi}", params={"email": email}, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        loc = (r.json() or {}).get("best_oa_location") or {}
        return loc.get("url_for_pdf") or loc.get("url")
    except Exception as e:
        logger.debug("unpaywall %s: %s", doi, e)
        return None
