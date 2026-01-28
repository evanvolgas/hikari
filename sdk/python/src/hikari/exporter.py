"""OTel SpanExporter that sends spans to the Hikari collector.

Batches spans (default 100 or 5s flush interval), uses a bounded in-memory
queue (max 10,000 spans), drops oldest on overflow, and retries with
exponential backoff. Never raises exceptions to user code.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Any, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger("hikari.exporter")

_RETRY_DELAYS = [1.0, 2.0, 4.0]  # exponential backoff


def _span_to_otlp_dict(span: ReadableSpan) -> dict[str, Any]:
    """Convert an OTel ReadableSpan to OTLP-compatible JSON dict."""
    attrs: list[dict[str, Any]] = []
    if span.attributes:
        for key, value in span.attributes.items():
            if isinstance(value, int):
                attrs.append({"key": key, "value": {"intValue": str(value)}})
            elif isinstance(value, float):
                attrs.append({"key": key, "value": {"doubleValue": value}})
            elif isinstance(value, str):
                attrs.append({"key": key, "value": {"stringValue": value}})
            elif isinstance(value, bool):
                attrs.append({"key": key, "value": {"boolValue": value}})

    context = span.get_span_context()
    trace_id = format(context.trace_id, "032x") if context else ""
    span_id = format(context.span_id, "016x") if context else ""

    start_ns = span.start_time or 0
    end_ns = span.end_time or 0

    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": span.name,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attrs,
    }


class HikariSpanExporter(SpanExporter):
    """Exports spans to the Hikari collector via HTTP POST."""

    def __init__(
        self,
        endpoint: str = "http://localhost:8000",
        max_queue_size: int = 10_000,
        batch_size: int = 100,
        flush_interval_seconds: float = 5.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._max_queue_size = max_queue_size
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._queue: deque[ReadableSpan] = deque(maxlen=max_queue_size)
        self._lock = threading.Lock()
        self._shutdown = False

        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="hikari-exporter-flush"
        )
        self._flush_thread.start()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Enqueue spans for batch export. Never raises."""
        if self._shutdown:
            return SpanExportResult.SUCCESS

        try:
            with self._lock:
                for span in spans:
                    self._queue.append(span)
                    # deque(maxlen=...) automatically drops oldest on overflow

                if len(self._queue) >= self._batch_size:
                    self._flush_batch()
        except Exception:
            logger.debug("Error enqueueing spans", exc_info=True)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Flush remaining spans and stop the background thread."""
        self._shutdown = True
        try:
            with self._lock:
                self._flush_batch()
        except Exception:
            logger.debug("Error during shutdown flush", exc_info=True)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Flush all queued spans."""
        try:
            with self._lock:
                self._flush_batch()
            return True
        except Exception:
            logger.debug("Error during force flush", exc_info=True)
            return False

    def _flush_loop(self) -> None:
        """Background thread that flushes on interval."""
        while not self._shutdown:
            time.sleep(self._flush_interval)
            try:
                with self._lock:
                    if self._queue:
                        self._flush_batch()
            except Exception:
                logger.debug("Error in flush loop", exc_info=True)

    def _flush_batch(self) -> None:
        """Send queued spans to collector. Caller must hold ``self._lock``."""
        if not self._queue:
            return

        batch: list[ReadableSpan] = []
        while self._queue and len(batch) < self._batch_size:
            batch.append(self._queue.popleft())

        if not batch:
            return

        otlp_spans = [_span_to_otlp_dict(s) for s in batch]
        payload = {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {"spans": otlp_spans}
                    ]
                }
            ]
        }

        self._send_with_retry(payload)

    def _send_with_retry(self, payload: dict[str, Any]) -> None:
        """Send payload with exponential backoff retries."""
        import httpx

        url = f"{self._endpoint}/v1/traces"
        body = json.dumps(payload).encode("utf-8")

        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                response = httpx.post(
                    url,
                    content=body,
                    headers={"Content-Type": "application/json"},
                    timeout=5.0,
                )
                if response.status_code < 300:
                    return
                logger.debug(
                    "Collector returned %d on attempt %d", response.status_code, attempt + 1
                )
            except Exception:
                logger.debug("Send failed on attempt %d", attempt + 1, exc_info=True)

            if attempt < len(_RETRY_DELAYS) - 1:
                time.sleep(delay)

        logger.warning("Dropped batch after %d retries", len(_RETRY_DELAYS))
