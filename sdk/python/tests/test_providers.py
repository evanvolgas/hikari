"""Tests for provider monkey-patches.

Uses mock objects to simulate provider responses without needing
real provider SDKs installed (beyond their importability).
"""

from __future__ import annotations

import asyncio
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hikari import attributes
from hikari.pricing import PricingModel


class _MockUsageOpenAI:
    """Mimics openai response.usage."""

    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _MockOpenAIResponse:
    """Mimics an OpenAI ChatCompletion response."""

    def __init__(
        self,
        model: str = "gpt-4o",
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ) -> None:
        self.model = model
        self.usage = _MockUsageOpenAI(prompt_tokens, completion_tokens)


class _MockUsageAnthropic:
    """Mimics anthropic response.usage."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _MockAnthropicResponse:
    """Mimics an Anthropic Messages response."""

    def __init__(
        self,
        model: str = "claude-3-haiku-20240307",
        input_tokens: int = 80,
        output_tokens: int = 40,
    ) -> None:
        self.model = model
        self.usage = _MockUsageAnthropic(input_tokens, output_tokens)


class _MockGoogleUsageMetadata:
    """Mimics google response.usage_metadata."""

    def __init__(self, prompt_token_count: int, candidates_token_count: int) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class _MockGoogleResponse:
    """Mimics a Google GenerateContent response."""

    def __init__(
        self,
        prompt_token_count: int = 60,
        candidates_token_count: int = 30,
    ) -> None:
        self.usage_metadata = _MockGoogleUsageMetadata(
            prompt_token_count, candidates_token_count
        )


class TestOpenAIPatch:
    def test_openai_patch_sets_span_attributes(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        from hikari.providers import openai as openai_patch

        pricing = PricingModel()
        mock_response = _MockOpenAIResponse(
            model="gpt-4o", prompt_tokens=150, completion_tokens=50
        )

        # Create a mock Completions class to patch
        original_create = MagicMock(return_value=mock_response)

        wrapper = openai_patch._make_sync_wrapper(original_create, pricing)
        mock_self = MagicMock()
        result = wrapper(mock_self, model="gpt-4o")

        assert result is mock_response
        original_create.assert_called_once()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "openai.chat.completions.create"

        span_attrs = dict(span.attributes or {})
        assert span_attrs[attributes.PROVIDER] == "openai"
        assert span_attrs[attributes.MODEL] == "gpt-4o"
        assert span_attrs[attributes.TOKENS_INPUT] == 150
        assert span_attrs[attributes.TOKENS_OUTPUT] == 50
        assert attributes.COST_TOTAL in span_attrs
        assert span_attrs[attributes.COST_TOTAL] > 0

    def test_provider_error_does_not_propagate(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """If Hikari internals raise, the original response is still returned."""
        from hikari.providers import openai as openai_patch

        mock_response = _MockOpenAIResponse()
        original_create = MagicMock(return_value=mock_response)

        # Pass a broken pricing model to trigger an internal error
        broken_pricing = MagicMock()
        broken_pricing.compute_cost.side_effect = RuntimeError("boom")

        wrapper = openai_patch._make_sync_wrapper(original_create, broken_pricing)
        mock_self = MagicMock()
        result = wrapper(mock_self, model="gpt-4o")

        # The original response must still be returned
        assert result is mock_response


class TestAnthropicPatch:
    def test_anthropic_patch_sets_span_attributes(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        from hikari.providers import anthropic as anthropic_patch

        pricing = PricingModel()
        mock_response = _MockAnthropicResponse(
            model="claude-3-haiku-20240307", input_tokens=80, output_tokens=40
        )

        original_create = MagicMock(return_value=mock_response)
        wrapper = anthropic_patch._make_sync_wrapper(original_create, pricing)
        mock_self = MagicMock()
        result = wrapper(mock_self, model="claude-3-haiku-20240307")

        assert result is mock_response

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "anthropic.messages.create"

        span_attrs = dict(span.attributes or {})
        assert span_attrs[attributes.PROVIDER] == "anthropic"
        assert span_attrs[attributes.MODEL] == "claude-3-haiku-20240307"
        assert span_attrs[attributes.TOKENS_INPUT] == 80
        assert span_attrs[attributes.TOKENS_OUTPUT] == 40


class TestGooglePatch:
    def test_google_patch_sets_span_attributes(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        from hikari.providers import google as google_patch

        pricing = PricingModel()
        mock_response = _MockGoogleResponse(
            prompt_token_count=60, candidates_token_count=30
        )

        original_create = MagicMock(return_value=mock_response)
        wrapper = google_patch._make_sync_wrapper(original_create, pricing)

        # Mock self with model_name attribute
        mock_self = MagicMock()
        mock_self.model_name = "models/gemini-1.5-pro"

        result = wrapper(mock_self, "Hello")

        assert result is mock_response

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "google.generativeai.generate_content"

        span_attrs = dict(span.attributes or {})
        assert span_attrs[attributes.PROVIDER] == "google"
        assert span_attrs[attributes.MODEL] == "gemini-1.5-pro"  # stripped "models/" prefix
        assert span_attrs[attributes.TOKENS_INPUT] == 60
        assert span_attrs[attributes.TOKENS_OUTPUT] == 30


class TestNullTokenHandling:
    def test_missing_usage_produces_no_token_attributes(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        from hikari.providers import openai as openai_patch

        pricing = PricingModel()

        # Response with no usage
        mock_response = MagicMock(spec=[])
        mock_response.model = "gpt-4o"

        original_create = MagicMock(return_value=mock_response)
        wrapper = openai_patch._make_sync_wrapper(original_create, pricing)
        mock_self = MagicMock()
        wrapper(mock_self, model="gpt-4o")

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span_attrs = dict(spans[0].attributes or {})

        # Token attributes should not be set when usage is missing
        assert attributes.TOKENS_INPUT not in span_attrs
        assert attributes.TOKENS_OUTPUT not in span_attrs
        assert attributes.COST_TOTAL not in span_attrs


class TestAsyncOpenAIPatch:
    """Tests for async OpenAI provider wrapper."""

    @pytest.mark.asyncio
    async def test_async_openai_patch_sets_span_attributes(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """Verify async wrapper correctly captures span attributes."""
        from hikari.providers import openai as openai_patch

        pricing = PricingModel()
        mock_response = _MockOpenAIResponse(
            model="gpt-4o", prompt_tokens=200, completion_tokens=100
        )

        # Create async mock that returns the response
        async def mock_async_create(*args: Any, **kwargs: Any) -> _MockOpenAIResponse:
            return mock_response

        original_create = AsyncMock(side_effect=mock_async_create)

        wrapper = openai_patch._make_async_wrapper(original_create, pricing)
        mock_self = MagicMock()
        result = await wrapper(mock_self, model="gpt-4o")

        assert result is mock_response
        original_create.assert_called_once()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "openai.chat.completions.create"

        span_attrs = dict(span.attributes or {})
        assert span_attrs[attributes.PROVIDER] == "openai"
        assert span_attrs[attributes.MODEL] == "gpt-4o"
        assert span_attrs[attributes.TOKENS_INPUT] == 200
        assert span_attrs[attributes.TOKENS_OUTPUT] == 100
        assert attributes.COST_TOTAL in span_attrs
        assert span_attrs[attributes.COST_TOTAL] > 0

    @pytest.mark.asyncio
    async def test_async_provider_error_does_not_propagate(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """If Hikari internals raise in async context, original response still returned."""
        from hikari.providers import openai as openai_patch

        mock_response = _MockOpenAIResponse()

        async def mock_async_create(*args: Any, **kwargs: Any) -> _MockOpenAIResponse:
            return mock_response

        original_create = AsyncMock(side_effect=mock_async_create)

        # Pass a broken pricing model to trigger an internal error
        broken_pricing = MagicMock()
        broken_pricing.compute_cost.side_effect = RuntimeError("async boom")

        wrapper = openai_patch._make_async_wrapper(original_create, broken_pricing)
        mock_self = MagicMock()
        result = await wrapper(mock_self, model="gpt-4o")

        # The original response must still be returned despite internal error
        assert result is mock_response

    @pytest.mark.asyncio
    async def test_async_openai_exception_propagates(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """Verify that exceptions from the actual provider call propagate correctly."""
        from hikari.providers import openai as openai_patch

        pricing = PricingModel()

        async def mock_failing_create(*args: Any, **kwargs: Any) -> None:
            raise ValueError("API error")

        original_create = AsyncMock(side_effect=mock_failing_create)

        wrapper = openai_patch._make_async_wrapper(original_create, pricing)
        mock_self = MagicMock()

        with pytest.raises(ValueError, match="API error"):
            await wrapper(mock_self, model="gpt-4o")

        # Span should still be created even on error
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1


class TestAsyncAnthropicPatch:
    """Tests for async Anthropic provider wrapper."""

    @pytest.mark.asyncio
    async def test_async_anthropic_patch_sets_span_attributes(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """Verify async wrapper correctly captures span attributes."""
        from hikari.providers import anthropic as anthropic_patch

        pricing = PricingModel()
        mock_response = _MockAnthropicResponse(
            model="claude-3-haiku-20240307", input_tokens=120, output_tokens=60
        )

        async def mock_async_create(*args: Any, **kwargs: Any) -> _MockAnthropicResponse:
            return mock_response

        original_create = AsyncMock(side_effect=mock_async_create)

        wrapper = anthropic_patch._make_async_wrapper(original_create, pricing)
        mock_self = MagicMock()
        result = await wrapper(mock_self, model="claude-3-haiku-20240307")

        assert result is mock_response
        original_create.assert_called_once()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "anthropic.messages.create"

        span_attrs = dict(span.attributes or {})
        assert span_attrs[attributes.PROVIDER] == "anthropic"
        assert span_attrs[attributes.MODEL] == "claude-3-haiku-20240307"
        assert span_attrs[attributes.TOKENS_INPUT] == 120
        assert span_attrs[attributes.TOKENS_OUTPUT] == 60

    @pytest.mark.asyncio
    async def test_async_anthropic_error_does_not_propagate(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """If Hikari internals raise in async context, original response still returned."""
        from hikari.providers import anthropic as anthropic_patch

        mock_response = _MockAnthropicResponse()

        async def mock_async_create(*args: Any, **kwargs: Any) -> _MockAnthropicResponse:
            return mock_response

        original_create = AsyncMock(side_effect=mock_async_create)

        broken_pricing = MagicMock()
        broken_pricing.compute_cost.side_effect = RuntimeError("async anthropic boom")

        wrapper = anthropic_patch._make_async_wrapper(original_create, broken_pricing)
        mock_self = MagicMock()
        result = await wrapper(mock_self, model="claude-3-haiku-20240307")

        # The original response must still be returned despite internal error
        assert result is mock_response

    @pytest.mark.asyncio
    async def test_async_anthropic_exception_propagates(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """Verify that exceptions from the actual provider call propagate correctly."""
        from hikari.providers import anthropic as anthropic_patch

        pricing = PricingModel()

        async def mock_failing_create(*args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Anthropic API error")

        original_create = AsyncMock(side_effect=mock_failing_create)

        wrapper = anthropic_patch._make_async_wrapper(original_create, pricing)
        mock_self = MagicMock()

        with pytest.raises(ConnectionError, match="Anthropic API error"):
            await wrapper(mock_self, model="claude-3-haiku-20240307")

        # Span should still be created even on error
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1


class TestAsyncNullTokenHandling:
    """Tests for async wrappers with missing token data."""

    @pytest.mark.asyncio
    async def test_async_missing_usage_produces_no_token_attributes(
        self, span_exporter: InMemorySpanExporter
    ) -> None:
        """Verify async wrapper handles missing usage gracefully."""
        from hikari.providers import openai as openai_patch

        pricing = PricingModel()

        # Response with no usage attribute
        mock_response = MagicMock(spec=[])
        mock_response.model = "gpt-4o"

        async def mock_async_create(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_response

        original_create = AsyncMock(side_effect=mock_async_create)
        wrapper = openai_patch._make_async_wrapper(original_create, pricing)
        mock_self = MagicMock()
        await wrapper(mock_self, model="gpt-4o")

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span_attrs = dict(spans[0].attributes or {})

        # Token attributes should not be set when usage is missing
        assert attributes.TOKENS_INPUT not in span_attrs
        assert attributes.TOKENS_OUTPUT not in span_attrs
        assert attributes.COST_TOTAL not in span_attrs
