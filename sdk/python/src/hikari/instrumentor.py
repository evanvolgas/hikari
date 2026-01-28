"""Auto-patching orchestrator.

Detects installed provider libraries and applies monkey-patches to capture
LLM call telemetry as OTel spans with ``hikari.*`` attributes.
"""

from __future__ import annotations

import logging
from typing import Any

from hikari.pricing import PricingModel
from hikari.providers import anthropic as anthropic_patch
from hikari.providers import google as google_patch
from hikari.providers import openai as openai_patch

logger = logging.getLogger("hikari.instrumentor")

_PATCHES = [
    ("openai", openai_patch),
    ("anthropic", anthropic_patch),
    ("google", google_patch),
]


class HikariInstrumentor:
    """Orchestrates monkey-patching of provider clients."""

    def __init__(self, pricing_model: PricingModel) -> None:
        self._pricing_model = pricing_model
        self._patched: list[str] = []

    def instrument(self) -> None:
        """Detect installed providers and patch them.

        For each provider:
        1. Try to import the provider module.
        2. If import fails -> skip (provider not installed).
        3. If import succeeds, check version meets minimum.
        4. If version too old -> log warning, skip.
        5. If version OK -> apply patch.
        """
        for name, patch_module in _PATCHES:
            try:
                success = patch_module.patch(self._pricing_model)
                if success:
                    self._patched.append(name)
            except Exception:
                logger.warning("Failed to instrument %s", name, exc_info=True)

    def uninstrument(self) -> None:
        """Restore all original methods."""
        for name, patch_module in _PATCHES:
            if name in self._patched:
                try:
                    patch_module.unpatch()
                except Exception:
                    logger.warning("Failed to uninstrument %s", name, exc_info=True)
        self._patched.clear()

    @property
    def patched_providers(self) -> list[str]:
        """Return list of successfully patched provider names."""
        return list(self._patched)
