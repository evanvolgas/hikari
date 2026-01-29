"""Tests for OTLP span ingestion endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ingest_valid_spans(client: AsyncClient) -> None:
    """Test ingestion of valid OTLP spans with Hikari attributes."""
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "abc123def456",
                                "spanId": "dead001beef",
                                "name": "llm.generate",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": [
                                    {"key": "hikari.stage", "value": "generation"},
                                    {"key": "hikari.model", "value": "gpt-4"},
                                    {"key": "hikari.provider", "value": "openai"},
                                    {"key": "hikari.tokens.input", "value": 100},
                                    {"key": "hikari.tokens.output", "value": 50},
                                    {"key": "hikari.cost.input", "value": 0.003},
                                    {"key": "hikari.cost.output", "value": 0.006},
                                    {"key": "hikari.cost.total", "value": 0.009},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    response = await client.post("/v1/traces", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_ingest_invalid_span_rejected(client: AsyncClient) -> None:
    """Test that spans missing required attributes are rejected."""
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "abc123def456",
                                "spanId": "dead001beef",
                                "name": "llm.generate",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": [
                                    # Missing hikari.stage, hikari.model, hikari.provider
                                    {"key": "hikari.tokens.input", "value": 100},
                                    {"key": "hikari.tokens.output", "value": 50},
                                ],
                            },
                            {
                                "traceId": "abc123def456",
                                "spanId": "dead002beef",
                                "name": "llm.generate",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": [
                                    {"key": "hikari.stage", "value": "generation"},
                                    {"key": "hikari.model", "value": "gpt-4"},
                                    {"key": "hikari.provider", "value": "openai"},
                                    {"key": "hikari.tokens.input", "value": 100},
                                    {"key": "hikari.tokens.output", "value": 50},
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
    }

    response = await client.post("/v1/traces", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 1
    assert len(data["errors"]) == 1
    assert "Missing required attributes" in data["errors"][0]


@pytest.mark.asyncio
async def test_ingest_empty_body(client: AsyncClient) -> None:
    """Test ingestion with empty resourceSpans list."""
    payload = {"resourceSpans": []}

    response = await client.post("/v1/traces", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 0
    assert data["rejected"] == 0
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_ingest_missing_token_counts_accepted(client: AsyncClient) -> None:
    """Test that spans without token counts are still accepted (tokens are optional)."""
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "abc123def456",
                                "spanId": "dead001beef",
                                "name": "llm.generate",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": [
                                    {"key": "hikari.stage", "value": "generation"},
                                    {"key": "hikari.model", "value": "gpt-4"},
                                    {"key": "hikari.provider", "value": "openai"},
                                    # No tokens — that's fine, they're optional
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    response = await client.post("/v1/traces", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0


@pytest.mark.asyncio
async def test_ingest_custom_pipeline_id(client: AsyncClient) -> None:
    """Test that custom hikari.pipeline_id is respected."""
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "face123def456",
                                "spanId": "dead001beef",
                                "name": "llm.generate",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": [
                                    {"key": "hikari.pipeline_id", "value": "custom-pipeline-456"},
                                    {"key": "hikari.stage", "value": "generation"},
                                    {"key": "hikari.model", "value": "gpt-4"},
                                    {"key": "hikari.provider", "value": "openai"},
                                    {"key": "hikari.tokens.input", "value": 100},
                                    {"key": "hikari.tokens.output", "value": 50},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    response = await client.post("/v1/traces", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1


@pytest.mark.asyncio
async def test_ingest_otlp_typed_values(client: AsyncClient) -> None:
    """Test that OTLP typed attribute values (stringValue, intValue, etc.) are handled."""
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "abc123def456",
                                "spanId": "dead001beef",
                                "name": "llm.generate",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": [
                                    {"key": "hikari.stage", "value": {"stringValue": "generation"}},
                                    {"key": "hikari.model", "value": {"stringValue": "gpt-4"}},
                                    {"key": "hikari.provider", "value": {"stringValue": "openai"}},
                                    {"key": "hikari.tokens.input", "value": {"intValue": 100}},
                                    {"key": "hikari.tokens.output", "value": {"intValue": 50}},
                                    {"key": "hikari.cost.total", "value": {"doubleValue": 0.009}},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    response = await client.post("/v1/traces", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0
