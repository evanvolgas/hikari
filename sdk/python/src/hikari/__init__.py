"""Hikari — OpenTelemetry-based LLM pipeline cost intelligence.

Public API::

    import hikari

    hikari.configure()  # auto-instruments installed providers
    hikari.set_pipeline_id("my-pipeline")  # optional: explicit pipeline grouping
    hikari.set_stage("summarize")  # optional: override auto-derived stage name
    hikari.shutdown()  # flush and restore originals
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from hikari.context import get_pipeline_id as _get_pipeline_id
from hikari.context import get_stage as _get_stage
from hikari.context import set_pipeline_id as _set_pipeline_id
from hikari.context import set_stage as _set_stage
from hikari.exporter import HikariSpanExporter
from hikari.instrumentor import HikariInstrumentor
from hikari.pricing import PricingModel

logger = logging.getLogger("hikari")

_instrumentor: HikariInstrumentor | None = None
_exporter: HikariSpanExporter | None = None
_provider: TracerProvider | None = None


def configure(
    *,
    pricing: dict[str, dict[str, float]] | None = None,
    collector_endpoint: str = "http://localhost:8000",
    batch_size: int = 100,
    flush_interval_seconds: float = 5.0,
    max_queue_size: int = 10_000,
) -> None:
    """Initialize Hikari instrumentation. Call once at application startup.

    Auto-detects and patches installed provider clients (OpenAI, Anthropic, Google).
    Providers not installed are silently skipped.
    Providers installed but with incompatible versions log a warning and are skipped.
    """
    global _instrumentor, _exporter, _provider

    pricing_model = PricingModel(overrides=pricing)

    _exporter = HikariSpanExporter(
        endpoint=collector_endpoint,
        max_queue_size=max_queue_size,
        batch_size=batch_size,
        flush_interval_seconds=flush_interval_seconds,
    )

    _provider = TracerProvider()
    processor = BatchSpanProcessor(
        _exporter,
        max_queue_size=max_queue_size,
        max_export_batch_size=batch_size,
        schedule_delay_millis=int(flush_interval_seconds * 1000),
    )
    _provider.add_span_processor(processor)

    from opentelemetry import trace

    trace.set_tracer_provider(_provider)

    _instrumentor = HikariInstrumentor(pricing_model)
    _instrumentor.instrument()


def set_pipeline_id(pipeline_id: str) -> None:
    """Set explicit pipeline ID on the current span context.

    Propagates to child spans via OTel context.
    If not called, pipeline_id defaults to the trace_id.
    """
    _set_pipeline_id(pipeline_id)


def set_stage(stage: str) -> None:
    """Override the auto-derived stage name on the current span context.

    Default stage is ``'{provider}.{operation}'``
    (e.g., ``'openai.chat.completions.create'``).
    """
    _set_stage(stage)


def shutdown() -> None:
    """Flush pending spans and restore original provider methods."""
    global _instrumentor, _exporter, _provider

    if _instrumentor:
        _instrumentor.uninstrument()
        _instrumentor = None

    if _provider:
        _provider.shutdown()
        _provider = None

    _exporter = None
