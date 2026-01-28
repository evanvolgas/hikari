"""End-to-end integration test: SDK -> Collector -> Query roundtrip.

Requires docker-compose running (PostgreSQL + TimescaleDB + Collector).
Run with: pytest tests/integration/ -m integration
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import httpx
import pytest

COLLECTOR_URL = "http://localhost:8000"


def _make_otlp_payload(
    trace_id: str,
    span_id: str,
    pipeline_id: str,
    stage: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    cost_input: float | None = None,
    cost_output: float | None = None,
    cost_total: float | None = None,
    duration_ns: int = 1_000_000_000,
) -> dict:
    """Build an OTLP-compatible JSON payload for a single span."""
    now_ns = int(time.time() * 1e9)
    attrs = [
        {"key": "hikari.pipeline_id", "value": {"stringValue": pipeline_id}},
        {"key": "hikari.stage", "value": {"stringValue": stage}},
        {"key": "hikari.model", "value": {"stringValue": model}},
        {"key": "hikari.provider", "value": {"stringValue": provider}},
        {"key": "hikari.tokens.input", "value": {"intValue": str(input_tokens)}},
        {"key": "hikari.tokens.output", "value": {"intValue": str(output_tokens)}},
    ]
    if cost_input is not None:
        attrs.append({"key": "hikari.cost.input", "value": {"doubleValue": cost_input}})
    if cost_output is not None:
        attrs.append({"key": "hikari.cost.output", "value": {"doubleValue": cost_output}})
    if cost_total is not None:
        attrs.append({"key": "hikari.cost.total", "value": {"doubleValue": cost_total}})

    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": stage,
                                "startTimeUnixNano": str(now_ns),
                                "endTimeUnixNano": str(now_ns + duration_ns),
                                "attributes": attrs,
                            }
                        ]
                    }
                ]
            }
        ]
    }


@pytest.mark.integration
class TestEndToEnd:
    """Full roundtrip: ingest spans, then query pipeline cost."""

    def test_health_endpoint(self) -> None:
        """Collector health endpoint should respond."""
        response = httpx.get(f"{COLLECTOR_URL}/v1/health", timeout=5.0)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert "version" in data

    def test_ingest_and_query_pipeline(self) -> None:
        """Ingest spans for a pipeline, then query its cost breakdown."""
        pipeline_id = f"integration-test-{int(time.time())}"

        # Ingest two spans from different providers
        payload1 = _make_otlp_payload(
            trace_id="abc123",
            span_id=f"span-1-{int(time.time())}",
            pipeline_id=pipeline_id,
            stage="openai.chat.completions.create",
            model="gpt-4o",
            provider="openai",
            input_tokens=1000,
            output_tokens=500,
            cost_input=0.0025,
            cost_output=0.005,
            cost_total=0.0075,
        )
        payload2 = _make_otlp_payload(
            trace_id="abc123",
            span_id=f"span-2-{int(time.time())}",
            pipeline_id=pipeline_id,
            stage="anthropic.messages.create",
            model="claude-3-haiku-20240307",
            provider="anthropic",
            input_tokens=800,
            output_tokens=200,
            cost_input=0.0002,
            cost_output=0.00025,
            cost_total=0.00045,
        )

        resp1 = httpx.post(
            f"{COLLECTOR_URL}/v1/traces", json=payload1, timeout=5.0
        )
        assert resp1.status_code == 200

        resp2 = httpx.post(
            f"{COLLECTOR_URL}/v1/traces", json=payload2, timeout=5.0
        )
        assert resp2.status_code == 200

        # Allow time for async writes
        time.sleep(1)

        # Query pipeline cost
        cost_resp = httpx.get(
            f"{COLLECTOR_URL}/v1/pipelines/{pipeline_id}/cost", timeout=5.0
        )
        assert cost_resp.status_code == 200
        cost_data = cost_resp.json()

        assert cost_data["pipeline_id"] == pipeline_id
        assert cost_data["is_partial"] is False
        assert cost_data["coverage_ratio"] == pytest.approx(1.0)
        assert len(cost_data["stages"]) == 2

        total = sum(s["cost_total"] for s in cost_data["stages"])
        assert cost_data["total_cost"] == pytest.approx(total)

    def test_partial_coverage_pipeline(self) -> None:
        """Pipeline with one unknown-cost span reports partial coverage."""
        pipeline_id = f"integration-partial-{int(time.time())}"

        # One span with cost
        payload1 = _make_otlp_payload(
            trace_id="def456",
            span_id=f"span-3-{int(time.time())}",
            pipeline_id=pipeline_id,
            stage="openai.chat.completions.create",
            model="gpt-4o",
            provider="openai",
            input_tokens=500,
            output_tokens=100,
            cost_input=0.00125,
            cost_output=0.001,
            cost_total=0.00225,
        )
        # One span without cost (unknown model)
        payload2 = _make_otlp_payload(
            trace_id="def456",
            span_id=f"span-4-{int(time.time())}",
            pipeline_id=pipeline_id,
            stage="anthropic.messages.create",
            model="unknown-model",
            provider="anthropic",
            input_tokens=300,
            output_tokens=50,
            # No cost fields
        )

        httpx.post(f"{COLLECTOR_URL}/v1/traces", json=payload1, timeout=5.0)
        httpx.post(f"{COLLECTOR_URL}/v1/traces", json=payload2, timeout=5.0)

        time.sleep(1)

        cost_resp = httpx.get(
            f"{COLLECTOR_URL}/v1/pipelines/{pipeline_id}/cost", timeout=5.0
        )
        assert cost_resp.status_code == 200
        cost_data = cost_resp.json()

        assert cost_data["is_partial"] is True
        assert cost_data["coverage_ratio"] == pytest.approx(0.5)

    def test_pipeline_list(self) -> None:
        """List pipelines endpoint returns results."""
        response = httpx.get(
            f"{COLLECTOR_URL}/v1/pipelines", params={"limit": 10}, timeout=5.0
        )
        assert response.status_code == 200
        data = response.json()
        assert "pipelines" in data
        assert "total" in data
        assert data["limit"] == 10
