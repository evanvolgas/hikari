"""Tests for pipeline cost queries."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from collector.queries import get_pipeline_cost, list_pipelines


@pytest.mark.asyncio
async def test_pipeline_cost_full_coverage() -> None:
    """Test pipeline cost query with full cost coverage."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    first_seen = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    last_seen = datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc)

    mock_conn.fetch.return_value = [
        {
            "stage": "generation",
            "model": "gpt-4",
            "provider": "openai",
            "tokens_input": 100,
            "tokens_output": 50,
            "cost_input": 0.003,
            "cost_output": 0.006,
            "cost_total": 0.009,
            "span_count": 1,
            "first_seen": first_seen,
            "last_seen": last_seen,
        },
        {
            "stage": "embedding",
            "model": "text-embedding-ada-002",
            "provider": "openai",
            "tokens_input": 200,
            "tokens_output": 0,
            "cost_input": 0.0001,
            "cost_output": 0.0,
            "cost_total": 0.0001,
            "span_count": 1,
            "first_seen": first_seen,
            "last_seen": last_seen,
        },
    ]

    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    result = await get_pipeline_cost(mock_pool, "pipeline123")

    assert result is not None
    assert result.pipeline_id == "pipeline123"
    assert result.total_cost == pytest.approx(0.0091)
    assert result.is_partial is False
    assert result.coverage_ratio == 1.0
    assert len(result.stages) == 2
    assert result.stages[0].stage == "generation"
    assert result.stages[1].stage == "embedding"
    assert result.first_seen == first_seen
    assert result.last_seen == last_seen


@pytest.mark.asyncio
async def test_pipeline_cost_partial() -> None:
    """Test pipeline cost query with partial cost coverage."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    ts = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    mock_conn.fetch.return_value = [
        {
            "stage": "generation",
            "model": "gpt-4",
            "provider": "openai",
            "tokens_input": 100,
            "tokens_output": 50,
            "cost_input": 0.003,
            "cost_output": 0.006,
            "cost_total": 0.009,
            "span_count": 1,
            "first_seen": ts,
            "last_seen": ts,
        },
        {
            "stage": "unknown-stage",
            "model": "custom-model",
            "provider": "custom",
            "tokens_input": 200,
            "tokens_output": 100,
            "cost_input": None,
            "cost_output": None,
            "cost_total": None,
            "span_count": 1,
            "first_seen": ts,
            "last_seen": ts,
        },
    ]

    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    result = await get_pipeline_cost(mock_pool, "pipeline456")

    assert result is not None
    assert result.pipeline_id == "pipeline456"
    # When a stage has null cost, total_cost should be 0.0 (null becomes 0.0 in response)
    # and is_partial should be True
    assert result.is_partial is True
    assert result.coverage_ratio == 0.5
    assert len(result.stages) == 2


@pytest.mark.asyncio
async def test_pipeline_cost_not_found() -> None:
    """Test pipeline cost query for non-existent pipeline."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    mock_conn.fetch.return_value = []

    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    result = await get_pipeline_cost(mock_pool, "nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_pipeline_list() -> None:
    """Test pipeline list query with pagination."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    mock_conn.fetchrow.return_value = {"total": 3}

    mock_conn.fetch.return_value = [
        {
            "pipeline_id": "pipeline1",
            "first_seen": datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            "last_seen": datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
            "span_count": 5,
            "total_cost": 0.05,
            "is_partial": False,
        },
        {
            "pipeline_id": "pipeline2",
            "first_seen": datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            "last_seen": datetime(2024, 1, 1, 11, 3, 0, tzinfo=timezone.utc),
            "span_count": 3,
            "total_cost": 0.0,
            "is_partial": True,
        },
    ]

    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    result = await list_pipelines(
        mock_pool,
        start=None,
        end=None,
        limit=2,
        offset=0,
    )

    assert result.total == 3
    assert result.limit == 2
    assert result.offset == 0
    assert len(result.pipelines) == 2
    assert result.pipelines[0].pipeline_id == "pipeline1"
    assert result.pipelines[0].is_partial is False
    assert result.pipelines[1].pipeline_id == "pipeline2"
    assert result.pipelines[1].is_partial is True


@pytest.mark.asyncio
async def test_pipeline_list_with_time_filter() -> None:
    """Test pipeline list query with time filtering."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    mock_conn.fetchrow.return_value = {"total": 1}
    mock_conn.fetch.return_value = [
        {
            "pipeline_id": "pipeline1",
            "first_seen": datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            "last_seen": datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
            "span_count": 5,
            "total_cost": 0.05,
            "is_partial": False,
        }
    ]

    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    start_time = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    result = await list_pipelines(
        mock_pool,
        start=start_time,
        end=end_time,
        limit=100,
        offset=0,
    )

    assert result.total == 1
    assert len(result.pipelines) == 1
