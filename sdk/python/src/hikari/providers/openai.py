"""OpenAI provider monkey-patch.

Target: ``openai.resources.chat.completions.Completions.create``
         ``openai.resources.chat.completions.AsyncCompletions.create``
Min version: openai >= 1.0
Response token path: ``response.usage.prompt_tokens``, ``response.usage.completion_tokens``
Model path: ``response.model`` (or request kwarg ``model``)
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable

from opentelemetry import trace

from hikari import attributes
from hikari.context import get_pipeline_id, get_stage

logger = logging.getLogger("hikari.providers.openai")

MIN_VERSION = "1.0"
PROVIDER_NAME = "openai"
_originals: dict[str, Any] = {}

tracer = trace.get_tracer("hikari")


def _extract_tokens(response: Any) -> tuple[int | None, int | None]:
    """Extract token counts from an OpenAI response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return (None, None)
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )


def _extract_model(response: Any, kwargs: dict[str, Any]) -> str:
    """Extract the model identifier from response or request kwargs."""
    model = getattr(response, "model", None)
    if model is None:
        model = kwargs.get("model", "unknown")
    return model


def _make_sync_wrapper(
    original: Callable[..., Any],
    pricing_model: Any,
) -> Callable[..., Any]:
    @functools.wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        span_name = "openai.chat.completions.create"
        stage = get_stage() or span_name
        with tracer.start_as_current_span(span_name) as span:
            try:
                response = original(self, *args, **kwargs)
            except Exception:
                raise
            else:
                try:
                    input_tokens, output_tokens = _extract_tokens(response)
                    model = _extract_model(response, kwargs)
                    pipeline_id = get_pipeline_id()
                    if pipeline_id:
                        span.set_attribute(attributes.PIPELINE_ID, pipeline_id)
                    span.set_attribute(attributes.STAGE, stage)
                    span.set_attribute(attributes.MODEL, model)
                    span.set_attribute(attributes.PROVIDER, PROVIDER_NAME)
                    if input_tokens is not None:
                        span.set_attribute(attributes.TOKENS_INPUT, input_tokens)
                    if output_tokens is not None:
                        span.set_attribute(attributes.TOKENS_OUTPUT, output_tokens)

                    input_cost, output_cost, total_cost = pricing_model.compute_cost(
                        PROVIDER_NAME, model, input_tokens, output_tokens
                    )
                    if input_cost is not None:
                        span.set_attribute(attributes.COST_INPUT, input_cost)
                    if output_cost is not None:
                        span.set_attribute(attributes.COST_OUTPUT, output_cost)
                    if total_cost is not None:
                        span.set_attribute(attributes.COST_TOTAL, total_cost)
                except Exception:
                    logger.debug("Failed to set span attributes", exc_info=True)
                return response

    return wrapper


def _make_async_wrapper(
    original: Callable[..., Any],
    pricing_model: Any,
) -> Callable[..., Any]:
    @functools.wraps(original)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        span_name = "openai.chat.completions.create"
        stage = get_stage() or span_name
        with tracer.start_as_current_span(span_name) as span:
            try:
                response = await original(self, *args, **kwargs)
            except Exception:
                raise
            else:
                try:
                    input_tokens, output_tokens = _extract_tokens(response)
                    model = _extract_model(response, kwargs)
                    pipeline_id = get_pipeline_id()
                    if pipeline_id:
                        span.set_attribute(attributes.PIPELINE_ID, pipeline_id)
                    span.set_attribute(attributes.STAGE, stage)
                    span.set_attribute(attributes.MODEL, model)
                    span.set_attribute(attributes.PROVIDER, PROVIDER_NAME)
                    if input_tokens is not None:
                        span.set_attribute(attributes.TOKENS_INPUT, input_tokens)
                    if output_tokens is not None:
                        span.set_attribute(attributes.TOKENS_OUTPUT, output_tokens)

                    input_cost, output_cost, total_cost = pricing_model.compute_cost(
                        PROVIDER_NAME, model, input_tokens, output_tokens
                    )
                    if input_cost is not None:
                        span.set_attribute(attributes.COST_INPUT, input_cost)
                    if output_cost is not None:
                        span.set_attribute(attributes.COST_OUTPUT, output_cost)
                    if total_cost is not None:
                        span.set_attribute(attributes.COST_TOTAL, total_cost)
                except Exception:
                    logger.debug("Failed to set span attributes", exc_info=True)
                return response

    return wrapper


def patch(pricing_model: Any) -> bool:
    """Apply monkey-patch to OpenAI client methods.

    Returns ``True`` if patch was applied, ``False`` if skipped.
    """
    try:
        import openai  # noqa: F811
    except ImportError:
        logger.debug("openai not installed, skipping")
        return False

    try:
        from packaging.version import Version
    except ImportError:
        # Fallback: try parsing version manually
        version_str = getattr(openai, "__version__", "0.0.0")
        major = int(version_str.split(".")[0])
        if major < 1:
            logger.warning("openai version %s < %s, skipping", version_str, MIN_VERSION)
            return False
    else:
        version_str = getattr(openai, "__version__", "0.0.0")
        if Version(version_str) < Version(MIN_VERSION):
            logger.warning("openai version %s < %s, skipping", version_str, MIN_VERSION)
            return False

    try:
        from openai.resources.chat.completions import AsyncCompletions, Completions

        _originals["sync_create"] = Completions.create
        _originals["async_create"] = AsyncCompletions.create

        Completions.create = _make_sync_wrapper(Completions.create, pricing_model)  # type: ignore[assignment]
        AsyncCompletions.create = _make_async_wrapper(AsyncCompletions.create, pricing_model)  # type: ignore[assignment]
        logger.info("Patched openai %s", version_str)
        return True
    except Exception:
        logger.warning("Failed to patch openai", exc_info=True)
        return False


def unpatch() -> None:
    """Restore original OpenAI methods."""
    try:
        from openai.resources.chat.completions import AsyncCompletions, Completions

        if "sync_create" in _originals:
            Completions.create = _originals.pop("sync_create")  # type: ignore[assignment]
        if "async_create" in _originals:
            AsyncCompletions.create = _originals.pop("async_create")  # type: ignore[assignment]
    except ImportError:
        pass
