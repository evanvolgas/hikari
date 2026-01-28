"""Shared test fixtures for the Hikari Python SDK."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Single global provider + exporter for the entire test session.
# OTel only allows set_tracer_provider once per process.
_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture()
def span_exporter() -> InMemorySpanExporter:
    """In-memory span exporter for capturing spans in tests.

    Clears captured spans before each test so tests are isolated.
    """
    _exporter.clear()
    return _exporter
