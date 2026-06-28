"""scinex config."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
KEYS_FILE = Path(os.environ.get("SCINEX_KEYS_FILE") or (Path.cwd()/".env" if (Path.cwd()/".env").exists() else (Path.home()/".api_keys" if (Path.home()/".api_keys").exists() else "/root/.api_keys")))
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
GOLD_DIR = ROOT / "eval" / "gold"

# LLM channels — see lib/llm_clients.MODELS
BULK_MODEL = "deepseek-v4-pro"      # OpenRouter, direct, cheap, 1M ctx — mass extraction
CRITIC_MODEL = "gemini-pro"         # fast (~7s) second pass / critic
RECONCILE_MODEL = "claude-opus"     # Opus 4.8 (max effort) — hard cases / tie-breaks. (Fable suspended.)
SUMMARIZE_MODEL = "gemini-pro"      # synthesis / review (1M ctx, fast); swap to claude-opus for polish

# Domain layer: None = domain-agnostic core. Set to a registered preset name
# (e.g. "chemistry", "longevity") to specialize extraction + validation. See domains/.
DEFAULT_DOMAIN = None

# Open enrichment APIs (no RU proxy needed)
S2_BASE = "https://api.semanticscholar.org/graph/v1"
OPENALEX_BASE = "https://api.openalex.org"

def env(name, default=None):
    return os.environ.get(name, default)
