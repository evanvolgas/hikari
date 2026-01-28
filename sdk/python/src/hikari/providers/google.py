"""Google Generative AI provider monkey-patch.

Target: ``google.generativeai.GenerativeModel.generate_content``
Min version: google-generativeai >= 0.3
Response token path: ``response.usage_metadata.prompt_token_count``,
                     ``response.usage_metadata.candidates_token_count``
Model path: ``self.model_name`` on the ``GenerativeModel`` instance
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from opentelemetry import trace

from hikari import attributes
from hikari.context import get_pipeline_id, get_stage

logger = logging.getLogger("hikari.providers.google")

MIN_VERSION = "0.3"
PROVIDER_NAME = "google"
_originals: dict[str, Any] = {}

tracer = trace.get_tracer("hikari")


def _extract_tokens(response: Any) -> tuple[int | None, int | None]:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return (None, None)
    return (
        getattr(metadata, "prompt_token_count", None),
        getattr(metadata, "candidates_token_count", None),
    )


def _extract_model(model_instance: Any) -> str:
    model_name = getattr(model_instance, "model_name", None)
    if model_name is None:
        return "unknown"
    # Google prefixes with "models/" — strip it for consistent keys
    if model_name.startswith("models/"):
        model_name = model_name[len("models/"):]
    return model_name


def _make_sync_wrapper(
    original: Callable[..., Any],
    pricing_model: Any,
) -> Callable[..., Any]:
    @functools.wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        span_name = "google.generativeai.generate_content"
        stage = get_stage() or span_name
        with tracer.start_as_current_span(span_name) as span:
            try:
                response = original(self, *args, **kwargs)
            except Exception:
                raise
            else:
                try:
                    input_tokens, output_tokens = _extract_tokens(response)
                    model = _extract_model(self)
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
    """Apply monkey-patch to Google GenerativeModel."""
    try:
        import google.generativeai  # noqa: F811
    except ImportError:
        logger.debug("google-generativeai not installed, skipping")
        return False

    version_str = getattr(google.generativeai, "__version__", "0.0.0")
    try:
        from packaging.version import Version

        if Version(version_str) < Version(MIN_VERSION):
            logger.warning(
                "google-generativeai version %s < %s, skipping", version_str, MIN_VERSION
            )
            return False
    except ImportError:
        parts = version_str.split(".")
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        min_parts = MIN_VERSION.split(".")
        min_major, min_minor = int(min_parts[0]), int(min_parts[1]) if len(min_parts) > 1 else 0
        if (major, minor) < (min_major, min_minor):
            logger.warning(
                "google-generativeai version %s < %s, skipping", version_str, MIN_VERSION
            )
            return False

    try:
        from google.generativeai import GenerativeModel

        _originals["generate_content"] = GenerativeModel.generate_content
        GenerativeModel.generate_content = _make_sync_wrapper(  # type: ignore[assignment]
            GenerativeModel.generate_content, pricing_model
        )
        logger.info("Patched google-generativeai %s", version_str)
        return True
    except Exception:
        logger.warning("Failed to patch google-generativeai", exc_info=True)
        return False


def unpatch() -> None:
    """Restore original Google GenerativeModel methods."""
    try:
        from google.generativeai import GenerativeModel

        if "generate_content" in _originals:
            GenerativeModel.generate_content = _originals.pop("generate_content")  # type: ignore[assignment]
    except ImportError:
        pass
