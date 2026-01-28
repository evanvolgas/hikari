"""Shared pytest fixtures for Hikari Collector tests."""

from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from collector.app import app as actual_app
from collector.storage import SpanWriter


@pytest.fixture
def mock_writer() -> SpanWriter:
    """Create a mock SpanWriter for testing."""
    writer = MagicMock(spec=SpanWriter)
    writer.db_connected = True
    writer.buffer_usage.return_value = 0.0
    writer.write_spans = AsyncMock()
    writer.close = AsyncMock()
    writer._pool = MagicMock()
    return writer


@pytest.fixture
def test_app(mock_writer: SpanWriter) -> FastAPI:
    """Create a test FastAPI application with mocked dependencies."""
    app = actual_app
    app.state.writer = mock_writer
    app.state.version = "0.1.0-test"
    return app


@pytest_asyncio.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for testing."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
