"""Pluggable pricing model for per-token cost computation.

Three-tier loading with LiteLLM as the primary source:
1. User overrides (passed to configure())
2. LiteLLM's bundled model_cost database (1,700+ models, auto-updates)
3. HIKARI_PRICING_PATH env var file (organization defaults)

LiteLLM pricing includes:
- All major providers (OpenAI, Anthropic, Google, AWS Bedrock, Azure, etc.)
- Cache pricing (read and creation costs)
- Tiered pricing (>200k token rates for some models)
- Updates automatically with `pip install --upgrade litellm`
"""

from __future__ import annotations

import json
import logging
import os
from importlib import resources
from typing import Any

logger = logging.getLogger("hikari.pricing")

# Conservative fallback pricing for unknown models (never underreport)
# Based on GPT-4 tier: $10/1M input, $30/1M output
_FALLBACK_INPUT_PER_TOKEN = 10.0 / 1_000_000
_FALLBACK_OUTPUT_PER_TOKEN = 30.0 / 1_000_000


def _load_litellm_pricing() -> dict[str, dict[str, float]]:
    """Load pricing from LiteLLM's bundled model_cost database.

    Returns dict mapping 'provider/model' to pricing info.
    """
    try:
        import litellm

        pricing: dict[str, dict[str, float]] = {}

        for model_id, info in litellm.model_cost.items():
            if model_id == "sample_spec":
                continue
            if "input_cost_per_token" not in info:
                continue

            # LiteLLM uses various naming conventions:
            # - "gpt-4o" (OpenAI)
            # - "claude-3-5-sonnet-20241022" (Anthropic)
            # - "bedrock/anthropic.claude..." (AWS)
            # - "vertex_ai/gemini..." (Google)
            #
            # We normalize to provider/model format for consistency
            input_cost = info.get("input_cost_per_token", 0.0)
            output_cost = info.get("output_cost_per_token", 0.0)

            # Skip unreasonable pricing (data errors)
            if input_cost > 0.001 or output_cost > 0.001:  # > $1000/1M
                continue

            # Detect provider from model_id or litellm_provider field
            provider = _extract_provider(model_id, info)

            # Store both the original model_id and normalized version
            pricing[f"{provider}/{model_id}"] = {
                "input_cost_per_token": input_cost,
                "output_cost_per_token": output_cost,
            }

            # Also store without provider prefix for direct model lookups
            pricing[model_id] = {
                "input_cost_per_token": input_cost,
                "output_cost_per_token": output_cost,
            }

            # Handle cache pricing if available
            cache_read = info.get("cache_read_input_token_cost")
            cache_create = info.get("cache_creation_input_token_cost")
            if cache_read is not None:
                pricing[f"{provider}/{model_id}"]["cache_read_cost_per_token"] = cache_read
                pricing[model_id]["cache_read_cost_per_token"] = cache_read
            if cache_create is not None:
                pricing[f"{provider}/{model_id}"]["cache_create_cost_per_token"] = cache_create
                pricing[model_id]["cache_create_cost_per_token"] = cache_create

        logger.info(f"Loaded pricing for {len(pricing) // 2} models from LiteLLM")
        return pricing

    except ImportError:
        logger.debug("LiteLLM not installed, skipping bundled pricing")
        return {}
    except Exception:
        logger.warning("Failed to load LiteLLM pricing", exc_info=True)
        return {}


def _extract_provider(model_id: str, info: dict[str, Any]) -> str:
    """Extract provider name from model_id or LiteLLM info."""
    # Check litellm_provider field first
    if "litellm_provider" in info:
        provider = info["litellm_provider"].lower()
        # Normalize common variations
        if provider in ("openai", "azure", "azure_ai"):
            return "openai"
        if provider in ("anthropic", "bedrock"):
            return "anthropic"
        if provider in ("vertex_ai", "vertex_ai_beta", "gemini"):
            return "google"
        return provider

    # Infer from model_id prefix
    model_lower = model_id.lower()
    if model_lower.startswith(("gpt-", "o1-", "o3-", "text-embedding", "dall-e")):
        return "openai"
    if model_lower.startswith(("claude-", "anthropic")):
        return "anthropic"
    if model_lower.startswith(("gemini-", "palm", "vertex")):
        return "google"
    if model_lower.startswith("bedrock/"):
        return "bedrock"
    if model_lower.startswith("azure/"):
        return "azure"

    # Default to the prefix before first / or -
    if "/" in model_id:
        return model_id.split("/")[0].lower()

    return "unknown"


class PricingModel:
    """Loads and manages per-model token pricing.

    Lookup key format: ``'{provider}/{model}'``, e.g. ``'openai/gpt-4o'``.

    Pricing sources (in order of precedence):
    1. User overrides passed to constructor
    2. HIKARI_PRICING_PATH env var file
    3. LiteLLM bundled database (1,700+ models)
    4. Bundled default_pricing.json (fallback)
    """

    def __init__(self, overrides: dict[str, dict[str, float]] | None = None) -> None:
        self._table: dict[str, dict[str, float]] = {}
        self._load_litellm()
        self._load_defaults()
        self._load_env_file()
        if overrides:
            self._table.update(overrides)

    def _load_litellm(self) -> None:
        """Load LiteLLM bundled pricing (primary source)."""
        self._table.update(_load_litellm_pricing())

    def _load_defaults(self) -> None:
        """Load bundled ``default_pricing.json`` as fallback."""
        try:
            ref = resources.files("hikari").joinpath("default_pricing.json")
            data: dict[str, Any] = json.loads(ref.read_text(encoding="utf-8"))
            # Only add if not already present from LiteLLM
            for key, value in data.items():
                if key not in self._table:
                    self._table[key] = value
        except Exception:
            logger.debug("Failed to load bundled default pricing", exc_info=True)

    def _load_env_file(self) -> None:
        """Load pricing from ``HIKARI_PRICING_PATH`` if set."""
        path = os.environ.get("HIKARI_PRICING_PATH")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            self._table.update(data)
            logger.info(f"Loaded {len(data)} pricing overrides from {path}")
        except Exception:
            logger.warning("Failed to load pricing from %s", path, exc_info=True)

    def get(self, provider: str, model: str) -> tuple[float | None, float | None]:
        """Return ``(input_cost_per_token, output_cost_per_token)`` for the model.

        Tries multiple lookup strategies:
        1. Exact match: provider/model
        2. Model only (LiteLLM often stores without provider prefix)
        3. Normalized model name (strip date suffixes, etc.)

        Returns ``(None, None)`` if the model is not found anywhere.
        """
        # Strategy 1: Exact match
        key = f"{provider}/{model}"
        entry = self._table.get(key)
        if entry:
            return (entry.get("input_cost_per_token"), entry.get("output_cost_per_token"))

        # Strategy 2: Model only (LiteLLM style)
        entry = self._table.get(model)
        if entry:
            return (entry.get("input_cost_per_token"), entry.get("output_cost_per_token"))

        # Strategy 3: Try without date suffix (gpt-4o-2024-11-20 -> gpt-4o)
        base_model = self._strip_date_suffix(model)
        if base_model != model:
            entry = self._table.get(f"{provider}/{base_model}")
            if entry:
                return (entry.get("input_cost_per_token"), entry.get("output_cost_per_token"))
            entry = self._table.get(base_model)
            if entry:
                return (entry.get("input_cost_per_token"), entry.get("output_cost_per_token"))

        return (None, None)

    def _strip_date_suffix(self, model: str) -> str:
        """Strip date suffix from model name (e.g., gpt-4o-2024-11-20 -> gpt-4o)."""
        import re

        # Match patterns like -2024-11-20, -20241120, :20241120
        pattern = r"[-:]20\d{2}[-]?\d{2}[-]?\d{2}$"
        return re.sub(pattern, "", model)

    def compute_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_tokens: int | None = None,
        cache_creation_tokens: int | None = None,
    ) -> tuple[float | None, float | None, float | None]:
        """Return ``(input_cost, output_cost, total_cost)``.

        Includes cache costs if cache tokens are provided and the model
        supports cache pricing.

        Any component is ``None`` if tokens are ``None`` or model pricing is unknown.
        ``total_cost`` is ``None`` if either ``input_cost`` or ``output_cost`` is ``None``.

        For unknown models, uses conservative fallback pricing ($10/$30 per 1M tokens)
        to avoid underreporting costs.
        """
        input_rate, output_rate = self.get(provider, model)

        # Use conservative fallback for unknown models
        use_fallback = False
        if input_rate is None or output_rate is None:
            logger.warning(
                f"No pricing for {provider}/{model}, using conservative fallback "
                f"(${_FALLBACK_INPUT_PER_TOKEN * 1_000_000:.0f}/${_FALLBACK_OUTPUT_PER_TOKEN * 1_000_000:.0f} per 1M)"
            )
            input_rate = _FALLBACK_INPUT_PER_TOKEN
            output_rate = _FALLBACK_OUTPUT_PER_TOKEN
            use_fallback = True

        input_cost: float | None = None
        output_cost: float | None = None
        total_cost: float | None = None

        if input_tokens is not None:
            input_cost = input_rate * input_tokens

        if output_tokens is not None:
            output_cost = output_rate * output_tokens

        # Add cache costs if applicable
        if cache_read_tokens is not None and cache_read_tokens > 0:
            cache_read_rate = self._get_cache_read_rate(provider, model)
            if cache_read_rate is not None and input_cost is not None:
                input_cost += cache_read_rate * cache_read_tokens

        if cache_creation_tokens is not None and cache_creation_tokens > 0:
            cache_create_rate = self._get_cache_create_rate(provider, model)
            if cache_create_rate is not None and input_cost is not None:
                input_cost += cache_create_rate * cache_creation_tokens

        if input_cost is not None and output_cost is not None:
            total_cost = input_cost + output_cost

        return (input_cost, output_cost, total_cost)

    def _get_cache_read_rate(self, provider: str, model: str) -> float | None:
        """Get cache read cost per token if available."""
        for key in [f"{provider}/{model}", model]:
            entry = self._table.get(key)
            if entry and "cache_read_cost_per_token" in entry:
                return entry["cache_read_cost_per_token"]
        return None

    def _get_cache_create_rate(self, provider: str, model: str) -> float | None:
        """Get cache creation cost per token if available."""
        for key in [f"{provider}/{model}", model]:
            entry = self._table.get(key)
            if entry and "cache_create_cost_per_token" in entry:
                return entry["cache_create_cost_per_token"]
        return None

    def update(
        self, model_key: str, input_cost_per_token: float, output_cost_per_token: float
    ) -> None:
        """Update pricing at runtime. ``model_key`` format: ``'{provider}/{model}'``."""
        self._table[model_key] = {
            "input_cost_per_token": input_cost_per_token,
            "output_cost_per_token": output_cost_per_token,
        }

    def model_count(self) -> int:
        """Return the number of models with pricing data."""
        # Count unique models (keys without provider prefix)
        return len({k.split("/")[-1] if "/" in k else k for k in self._table})

    def has_model(self, provider: str, model: str) -> bool:
        """Check if pricing exists for a model."""
        input_rate, _ = self.get(provider, model)
        return input_rate is not None
