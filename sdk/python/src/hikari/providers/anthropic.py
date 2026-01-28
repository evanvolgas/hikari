"""Anthropic provider monkey-patch.

Target: ``anthropic.resources.messages.Messages.create``
         ``anthropic.resources.messages.AsyncMessages.create``
Min version: anthropic >= 0.18
Response token path: ``response.usage.input_tokens``, ``response.usage.output_tokens``
Model path: ``response.model`` (or request kwarg ``model``)
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from opentelemetry import trace

from hikari import attributes
from hikari.context import get_pipeline_id, get_stage

logger = logging.getLogger("hikari.providers.anthropic")

MIN_VERSION = "0.18"
PROVIDER_NAME = "anthropic"
_originals: dict[str, Any] = {}

tracer = trace.get_tracer("hikari")


def _extract_tokens(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return (None, None)
    return (
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )


def _extract_model(response: Any, kwargs: dict[str, Any]) -> str:
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
        span_name = "anthropic.messages.create"
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
        span_name = "anthropic.messages.create"
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
    """Apply monkey-patch to Anthropic client methods."""
    try:
        import anthropic  # noqa: F811
    except ImportError:
        logger.debug("anthropic not installed, skipping")
        return False

    version_str = getattr(anthropic, "__version__", "0.0.0")
    try:
        from packaging.version import Version

        if Version(version_str) < Version(MIN_VERSION):
            logger.warning("anthropic version %s < %s, skipping", version_str, MIN_VERSION)
            return False
    except ImportError:
        parts = version_str.split(".")
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        min_parts = MIN_VERSION.split(".")
        min_major, min_minor = int(min_parts[0]), int(min_parts[1]) if len(min_parts) > 1 else 0
        if (major, minor) < (min_major, min_minor):
            logger.warning("anthropic version %s < %s, skipping", version_str, MIN_VERSION)
            return False

    try:
        from anthropic.resources.messages import AsyncMessages, Messages

        _originals["sync_create"] = Messages.create
        _originals["async_create"] = AsyncMessages.create

        Messages.create = _make_sync_wrapper(Messages.create, pricing_model)  # type: ignore[assignment]
        AsyncMessages.create = _make_async_wrapper(AsyncMessages.create, pricing_model)  # type: ignore[assignment]
        logger.info("Patched anthropic %s", version_str)
        return True
    except Exception:
        logger.warning("Failed to patch anthropic", exc_info=True)
        return False


def unpatch() -> None:
    """Restore original Anthropic methods."""
    try:
        from anthropic.resources.messages import AsyncMessages, Messages

        if "sync_create" in _originals:
            Messages.create = _originals.pop("sync_create")  # type: ignore[assignment]
        if "async_create" in _originals:
            AsyncMessages.create = _originals.pop("async_create")  # type: ignore[assignment]
    except ImportError:
        pass
