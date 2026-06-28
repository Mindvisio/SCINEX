"""Importing this package registers all bundled domain presets."""
from domains import chemistry, longevity  # noqa: F401  (side effect: register presets)
from domains.base import REGISTRY, DomainPreset, get, register  # noqa: F401
