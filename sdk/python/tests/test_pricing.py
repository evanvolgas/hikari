"""Tests for hikari.pricing.PricingModel."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from hikari.pricing import (
    PricingModel,
    _FALLBACK_INPUT_PER_TOKEN,
    _FALLBACK_OUTPUT_PER_TOKEN,
)


class TestPricingModelDefaults:
    def test_default_pricing_loads(self) -> None:
        pm = PricingModel()
        input_rate, output_rate = pm.get("openai", "gpt-4o")
        assert input_rate is not None
        assert output_rate is not None
        assert input_rate == pytest.approx(0.0000025)
        assert output_rate == pytest.approx(0.00001)

    def test_all_default_models_present(self) -> None:
        pm = PricingModel()
        expected_keys = [
            ("openai", "gpt-4o"),
            ("openai", "gpt-4o-mini"),
            ("anthropic", "claude-3-5-sonnet-20241022"),
            ("anthropic", "claude-3-haiku-20240307"),
            ("google", "gemini-1.5-pro"),
            ("google", "gemini-1.5-flash"),
        ]
        for provider, model in expected_keys:
            input_rate, output_rate = pm.get(provider, model)
            assert input_rate is not None, f"Missing input rate for {provider}/{model}"
            assert output_rate is not None, f"Missing output rate for {provider}/{model}"


class TestPricingModelLookup:
    def test_unknown_model_returns_none(self) -> None:
        """Unknown models should return None for rates (get() returns raw lookup)."""
        pm = PricingModel()
        input_rate, output_rate = pm.get("openai", "nonexistent-model-xyz")
        assert input_rate is None
        assert output_rate is None

    def test_model_only_lookup_ignores_provider(self) -> None:
        """Known models are found via model-only lookup regardless of provider.

        LiteLLM stores models without provider prefix, so 'gpt-4o' is found
        even with an unknown provider. This is intentional for flexibility.
        """
        pm = PricingModel()
        input_rate, output_rate = pm.get("not-a-provider", "gpt-4o")
        # Should find gpt-4o via model-only lookup
        assert input_rate is not None
        assert output_rate is not None


class TestComputeCost:
    def test_compute_cost_with_known_model(self) -> None:
        pm = PricingModel()
        input_cost, output_cost, total_cost = pm.compute_cost(
            "openai", "gpt-4o", input_tokens=1000, output_tokens=500
        )
        assert input_cost == pytest.approx(0.0000025 * 1000)
        assert output_cost == pytest.approx(0.00001 * 500)
        assert total_cost == pytest.approx(input_cost + output_cost)  # type: ignore[operator]

    def test_compute_cost_with_null_tokens(self) -> None:
        pm = PricingModel()
        input_cost, output_cost, total_cost = pm.compute_cost(
            "openai", "gpt-4o", input_tokens=None, output_tokens=None
        )
        assert input_cost is None
        assert output_cost is None
        assert total_cost is None

    def test_compute_cost_partial_null_tokens(self) -> None:
        pm = PricingModel()
        input_cost, output_cost, total_cost = pm.compute_cost(
            "openai", "gpt-4o", input_tokens=1000, output_tokens=None
        )
        assert input_cost is not None
        assert output_cost is None
        assert total_cost is None  # total requires both components

    def test_compute_cost_unknown_model_uses_fallback(self) -> None:
        """Unknown models use conservative fallback pricing.

        This ensures we never underreport costs - unknown models get
        GPT-4 tier pricing ($10/$30 per 1M tokens) as a safe default.
        """
        pm = PricingModel()
        input_cost, output_cost, total_cost = pm.compute_cost(
            "openai", "nonexistent-model-xyz", input_tokens=1000, output_tokens=500
        )
        # Should use fallback pricing, not None
        expected_input = _FALLBACK_INPUT_PER_TOKEN * 1000
        expected_output = _FALLBACK_OUTPUT_PER_TOKEN * 500
        assert input_cost == pytest.approx(expected_input)
        assert output_cost == pytest.approx(expected_output)
        assert total_cost == pytest.approx(expected_input + expected_output)


class TestUpdatePricing:
    def test_update_pricing(self) -> None:
        pm = PricingModel()
        pm.update("openai/new-model", 0.001, 0.002)
        input_rate, output_rate = pm.get("openai", "new-model")
        assert input_rate == pytest.approx(0.001)
        assert output_rate == pytest.approx(0.002)

    def test_update_overrides_existing(self) -> None:
        pm = PricingModel()
        pm.update("openai/gpt-4o", 0.999, 0.888)
        input_rate, output_rate = pm.get("openai", "gpt-4o")
        assert input_rate == pytest.approx(0.999)
        assert output_rate == pytest.approx(0.888)


class TestEnvVarOverride:
    def test_env_var_override(self, tmp_path: object) -> None:
        pricing_data = {
            "openai/custom-model": {
                "input_cost_per_token": 0.01,
                "output_cost_per_token": 0.02,
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(pricing_data, f)
            tmp_file = f.name

        try:
            os.environ["HIKARI_PRICING_PATH"] = tmp_file
            pm = PricingModel()
            input_rate, output_rate = pm.get("openai", "custom-model")
            assert input_rate == pytest.approx(0.01)
            assert output_rate == pytest.approx(0.02)
            # Default models should still be present
            default_input, default_output = pm.get("openai", "gpt-4o")
            assert default_input is not None
        finally:
            os.environ.pop("HIKARI_PRICING_PATH", None)
            os.unlink(tmp_file)

    def test_override_dict_wins_over_all(self) -> None:
        overrides = {
            "openai/gpt-4o": {
                "input_cost_per_token": 0.5,
                "output_cost_per_token": 0.6,
            }
        }
        pm = PricingModel(overrides=overrides)
        input_rate, output_rate = pm.get("openai", "gpt-4o")
        assert input_rate == pytest.approx(0.5)
        assert output_rate == pytest.approx(0.6)
