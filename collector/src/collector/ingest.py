"""OTLP span parsing and validation for Hikari cost attributes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from collector.models import IngestRequest, Span, SpanAttribute

logger = logging.getLogger(__name__)

REQUIRED_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"hikari.stage", "hikari.model", "hikari.provider"}
)

# Timestamp validation bounds
# Minimum: January 1, 2020 00:00:00 UTC (reasonable lower bound for LLM telemetry)
MIN_TIMESTAMP_NS: Final[int] = 1577836800_000_000_000
# Maximum: 1 year from now (allows for clock skew but prevents far-future dates)
# This is computed at module load time but spans with future timestamps
# beyond 1 year are almost certainly malformed
MAX_TIMESTAMP_FUTURE_DAYS: Final[int] = 365

# Maximum allowed duration for a single span (24 hours in nanoseconds)
# Spans longer than this are likely malformed
MAX_SPAN_DURATION_NS: Final[int] = 24 * 60 * 60 * 1_000_000_000


def _get_max_timestamp_ns() -> int:
    """Get the maximum allowed timestamp (1 year from now in nanoseconds)."""
    future_date = datetime.now(timezone.utc) + timedelta(days=MAX_TIMESTAMP_FUTURE_DAYS)
    return int(future_date.timestamp() * 1_000_000_000)


def _validate_timestamp_ns(value: str, field_name: str) -> int:
    """Validate and parse a nanosecond timestamp string.

    Args:
        value: The timestamp string to validate
        field_name: Name of the field for error messages

    Returns:
        The parsed timestamp as an integer

    Raises:
        ValueError: If the timestamp is invalid or out of bounds
    """
    try:
        timestamp_ns = int(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field_name} must be a valid integer: {e}")

    if timestamp_ns < 0:
        raise ValueError(f"{field_name} cannot be negative")

    if timestamp_ns < MIN_TIMESTAMP_NS:
        raise ValueError(
            f"{field_name} is too old (before 2020-01-01). "
            f"Value: {timestamp_ns}, minimum: {MIN_TIMESTAMP_NS}"
        )

    max_ts = _get_max_timestamp_ns()
    if timestamp_ns > max_ts:
        raise ValueError(
            f"{field_name} is too far in the future (more than {MAX_TIMESTAMP_FUTURE_DAYS} days). "
            f"Value: {timestamp_ns}, maximum: {max_ts}"
        )

    return timestamp_ns


def _extract_attr_value(attr: SpanAttribute) -> Any:
    """Extract the typed value from an OTLP attribute value dict."""
    val = attr.value
    if isinstance(val, dict):
        if "stringValue" in val:
            return val["stringValue"]
        if "intValue" in val:
            return val["intValue"]
        if "doubleValue" in val:
            return val["doubleValue"]
        if "boolValue" in val:
            return val["boolValue"]
    # Plain value (test payloads may send raw values)
    return val


def parse_ingest_request(
    request: IngestRequest,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate OTLP ingestion request.

    Returns (valid_span_dicts, error_messages).
    """
    valid_spans: list[dict[str, Any]] = []
    errors: list[str] = []

    for resource_spans in request.resourceSpans:
        for scope_spans in resource_spans.scopeSpans:
            for span in scope_spans.spans:
                try:
                    span_dict = _parse_span(span)
                    valid_spans.append(span_dict)
                except ValueError as e:
                    errors.append(f"Span {span.spanId}: {e}")
                    logger.warning("Span %s rejected: %s", span.spanId, e)

    return valid_spans, errors


def _parse_span(span: Span) -> dict[str, Any]:
    """Parse a single OTLP span into a database-ready dict.

    Raises ValueError if required attributes are missing.
    """
    attrs: dict[str, Any] = {}
    for attr in span.attributes:
        attrs[attr.key] = _extract_attr_value(attr)

    missing = REQUIRED_ATTRIBUTES - set(attrs.keys())
    if missing:
        raise ValueError(f"Missing required attributes: {', '.join(sorted(missing))}")

    stage = attrs["hikari.stage"]
    model = attrs["hikari.model"]
    provider = attrs["hikari.provider"]
    pipeline_id = attrs.get("hikari.pipeline_id", span.traceId)

    tokens_input = attrs.get("hikari.tokens.input")
    tokens_output = attrs.get("hikari.tokens.output")

    # Costs are optional
    cost_input = attrs.get("hikari.cost.input")
    cost_output = attrs.get("hikari.cost.output")
    cost_total = attrs.get("hikari.cost.total")

    # Validate and convert nano timestamps
    start_ns = _validate_timestamp_ns(span.startTimeUnixNano, "startTimeUnixNano")
    end_ns = _validate_timestamp_ns(span.endTimeUnixNano, "endTimeUnixNano")

    # Validate temporal ordering
    if end_ns < start_ns:
        raise ValueError(
            f"endTimeUnixNano ({end_ns}) must be >= startTimeUnixNano ({start_ns})"
        )

    # Validate span duration is reasonable
    duration_ns = end_ns - start_ns
    if duration_ns > MAX_SPAN_DURATION_NS:
        raise ValueError(
            f"Span duration ({duration_ns / 1_000_000_000:.2f}s) exceeds maximum "
            f"allowed duration ({MAX_SPAN_DURATION_NS / 1_000_000_000:.0f}s)"
        )

    duration_ms = duration_ns / 1_000_000
    time = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=timezone.utc)

    # Type coercion
    if tokens_input is not None:
        tokens_input = int(tokens_input)
    if tokens_output is not None:
        tokens_output = int(tokens_output)
    if cost_input is not None:
        cost_input = float(cost_input)
    if cost_output is not None:
        cost_output = float(cost_output)
    if cost_total is not None:
        cost_total = float(cost_total)

    return {
        "time": time,
        "trace_id": span.traceId,
        "span_id": span.spanId,
        "span_name": span.name,
        "pipeline_id": pipeline_id,
        "stage": stage,
        "model": model,
        "provider": provider,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "cost_input": cost_input,
        "cost_output": cost_output,
        "cost_total": cost_total,
        "duration_ms": duration_ms,
    }
