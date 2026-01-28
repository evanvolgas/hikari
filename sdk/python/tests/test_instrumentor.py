"""Tests for hikari.instrumentor.HikariInstrumentor."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from hikari.instrumentor import HikariInstrumentor
from hikari.pricing import PricingModel


class TestInstrumentorPatchDetection:
    def test_instrument_skips_missing_provider(self, caplog: pytest.LogCaptureFixture) -> None:
        """If a provider is not importable, instrument() does not raise."""
        pricing = PricingModel()
        instrumentor = HikariInstrumentor(pricing)

        # Patch all provider modules to simulate missing imports
        with (
            patch("hikari.providers.openai.patch", return_value=False),
            patch("hikari.providers.anthropic.patch", return_value=False),
            patch("hikari.providers.google.patch", return_value=False),
        ):
            instrumentor.instrument()

        assert instrumentor.patched_providers == []

    def test_instrument_patches_available_provider(self) -> None:
        pricing = PricingModel()
        instrumentor = HikariInstrumentor(pricing)

        with (
            patch("hikari.providers.openai.patch", return_value=True),
            patch("hikari.providers.anthropic.patch", return_value=False),
            patch("hikari.providers.google.patch", return_value=False),
        ):
            instrumentor.instrument()

        assert "openai" in instrumentor.patched_providers
        assert "anthropic" not in instrumentor.patched_providers

    def test_uninstrument_restores_originals(self) -> None:
        pricing = PricingModel()
        instrumentor = HikariInstrumentor(pricing)

        with (
            patch("hikari.providers.openai.patch", return_value=True),
            patch("hikari.providers.anthropic.patch", return_value=True),
            patch("hikari.providers.google.patch", return_value=False),
            patch("hikari.providers.openai.unpatch") as mock_openai_unpatch,
            patch("hikari.providers.anthropic.unpatch") as mock_anthropic_unpatch,
        ):
            instrumentor.instrument()
            assert len(instrumentor.patched_providers) == 2

            instrumentor.uninstrument()
            mock_openai_unpatch.assert_called_once()
            mock_anthropic_unpatch.assert_called_once()
            assert instrumentor.patched_providers == []

    def test_instrument_logs_warning_for_patch_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        pricing = PricingModel()
        instrumentor = HikariInstrumentor(pricing)

        with (
            patch(
                "hikari.providers.openai.patch",
                side_effect=RuntimeError("patch failed"),
            ),
            patch("hikari.providers.anthropic.patch", return_value=False),
            patch("hikari.providers.google.patch", return_value=False),
            caplog.at_level(logging.WARNING, logger="hikari.instrumentor"),
        ):
            instrumentor.instrument()  # should not raise

        assert instrumentor.patched_providers == []
        assert "Failed to instrument openai" in caplog.text
