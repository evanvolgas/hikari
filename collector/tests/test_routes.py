"""Tests for API route health checks."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_healthy(client: AsyncClient, test_app) -> None:
    """Test health endpoint when database is connected and buffer is normal."""
    test_app.state.writer.db_connected = True
    test_app.state.writer.buffer_usage.return_value = 0.1

    response = await client.get("/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["db_connected"] is True
    assert data["buffer_usage"] == 0.1
    assert data["version"] == "0.1.0-test"


@pytest.mark.asyncio
async def test_health_degraded(client: AsyncClient, test_app) -> None:
    """Test health endpoint when database is disconnected but buffering."""
    test_app.state.writer.db_connected = False
    test_app.state.writer.buffer_usage.return_value = 0.5

    response = await client.get("/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["db_connected"] is False
    assert data["buffer_usage"] == 0.5


@pytest.mark.asyncio
async def test_health_unhealthy_buffer_full(client: AsyncClient, test_app) -> None:
    """Test health endpoint when buffer is full."""
    test_app.state.writer.db_connected = False
    test_app.state.writer.buffer_usage.return_value = 1.0

    response = await client.get("/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["db_connected"] is False
    assert data["buffer_usage"] == 1.0


@pytest.mark.asyncio
async def test_health_unhealthy_high_buffer_usage(client: AsyncClient, test_app) -> None:
    """Test health endpoint when buffer usage is critically high."""
    test_app.state.writer.db_connected = True
    test_app.state.writer.buffer_usage.return_value = 0.95

    response = await client.get("/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["db_connected"] is True
    assert data["buffer_usage"] == 0.95
