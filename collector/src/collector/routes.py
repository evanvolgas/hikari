"""FastAPI routes for Hikari Collector API."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, status

from collector.ingest import parse_ingest_request
from collector.models import (
    HealthResponse,
    IngestRequest,
    IngestResponse,
    PipelineCostResponse,
    PipelineListResponse,
    TrendingResponse,
)
from collector.queries import get_pipeline_cost, get_trending, list_pipelines

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/traces", response_model=IngestResponse)
async def ingest_traces(request_body: IngestRequest, request: Request) -> IngestResponse:
    """Ingest OTLP trace spans with Hikari cost attributes."""
    writer = request.app.state.writer

    valid_spans, errors = parse_ingest_request(request_body)

    if valid_spans:
        await writer.write_spans(valid_spans)

    return IngestResponse(
        accepted=len(valid_spans),
        rejected=len(errors),
        errors=errors,
    )


@router.get("/v1/pipelines/{pipeline_id}/cost", response_model=PipelineCostResponse)
async def get_pipeline_cost_endpoint(
    pipeline_id: str, request: Request
) -> PipelineCostResponse:
    """Get cost breakdown for a specific pipeline.

    Args:
        pipeline_id: Pipeline identifier (1-256 chars, alphanumeric with -_:.)
        request: FastAPI request object

    Returns:
        PipelineCostResponse with cost breakdown by stage

    Raises:
        HTTPException: 400 if pipeline_id is invalid
        HTTPException: 404 if pipeline not found
        HTTPException: 503 if database unavailable
    """
    writer = request.app.state.writer

    # Validate pipeline_id format before querying
    from collector.models import validate_pipeline_id

    try:
        validate_pipeline_id(pipeline_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    pool = writer.pool  # Use public accessor instead of _pool
    if not writer.db_connected or pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    result = await get_pipeline_cost(pool, pipeline_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )

    return result


@router.get("/v1/pipelines", response_model=PipelineListResponse)
async def list_pipelines_endpoint(
    request: Request,
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> PipelineListResponse:
    """List pipelines with pagination and optional time filtering.

    Args:
        request: FastAPI request object
        start: Filter pipelines with spans after this time (optional)
        end: Filter pipelines with spans before this time (optional)
        limit: Maximum number of pipelines to return (1-1000, default 100)
        offset: Number of pipelines to skip for pagination (default 0)

    Returns:
        PipelineListResponse with paginated pipeline summaries

    Raises:
        HTTPException: 503 if database unavailable
    """
    writer = request.app.state.writer

    pool = writer.pool  # Use public accessor
    if not writer.db_connected or pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    return await list_pipelines(pool, start, end, limit, offset)


@router.get("/v1/cost/trending", response_model=TrendingResponse)
async def get_trending_endpoint(
    request: Request,
    start: datetime = Query(..., description="Start of time range (inclusive)"),
    end: datetime = Query(..., description="End of time range (exclusive)"),
    interval: str = Query(
        ..., description="Aggregation interval: 'hour', 'day', or 'week'"
    ),
    group_by: str = Query(
        ..., description="Dimension to group by: 'model', 'provider', or 'stage'"
    ),
) -> TrendingResponse:
    """Get cost trending data over time with dimensional breakdown.

    Args:
        request: FastAPI request object
        start: Start of time range (inclusive)
        end: End of time range (exclusive)
        interval: Aggregation interval - 'hour', 'day', or 'week'
        group_by: Dimension to group by - 'model', 'provider', or 'stage'

    Returns:
        TrendingResponse with bucketed cost data and breakdowns

    Raises:
        HTTPException: 400 if interval or group_by are invalid
        HTTPException: 503 if database unavailable
    """
    writer = request.app.state.writer

    pool = writer.pool  # Use public accessor
    if not writer.db_connected or pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    try:
        return await get_trending(pool, start, end, interval, group_by)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/v1/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Health check endpoint."""
    writer = request.app.state.writer
    version: str = request.app.state.version

    buf = writer.buffer_usage()
    connected = writer.db_connected

    if connected and buf < 0.9:
        st = "healthy"
    elif not connected and buf < 1.0:
        st = "degraded"
    else:
        st = "unhealthy"

    return HealthResponse(
        status=st,
        db_connected=connected,
        buffer_usage=buf,
        version=version,
    )
