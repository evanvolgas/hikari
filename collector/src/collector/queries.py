"""Async PostgreSQL queries for pipeline cost analysis and trending."""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Final

import asyncpg

from collector.models import (
    PipelineCostResponse,
    PipelineListResponse,
    PipelineSummary,
    StageCost,
    TrendingBucket,
    TrendingBucketBreakdown,
    TrendingResponse,
)

logger = logging.getLogger(__name__)


# Safe SQL identifier mappings - prevents SQL injection by using pre-validated constants
# These are the ONLY allowed values for dynamic SQL column/interval selection


class TrendingInterval(str, Enum):
    """Valid trending aggregation intervals."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"


class TrendingGroupBy(str, Enum):
    """Valid trending group-by dimensions."""

    MODEL = "model"
    PROVIDER = "provider"
    STAGE = "stage"


# Pre-defined SQL query templates with safe column mappings
# Column names are hardcoded strings, never user input
_INTERVAL_TO_PG: Final[dict[TrendingInterval, str]] = {
    TrendingInterval.HOUR: "1 hour",
    TrendingInterval.DAY: "1 day",
    TrendingInterval.WEEK: "1 week",
}

# Pre-built query templates for each group_by option
# This eliminates string interpolation entirely - we select the right query
_TRENDING_QUERIES: Final[dict[TrendingGroupBy, str]] = {
    TrendingGroupBy.MODEL: """
        SELECT
            time_bucket($3::interval, time) as bucket,
            model as dimension,
            COALESCE(SUM(cost_total), 0) as cost,
            COUNT(*) as request_count
        FROM spans
        WHERE time >= $1 AND time < $2
        GROUP BY bucket, model
        ORDER BY bucket, model
    """,
    TrendingGroupBy.PROVIDER: """
        SELECT
            time_bucket($3::interval, time) as bucket,
            provider as dimension,
            COALESCE(SUM(cost_total), 0) as cost,
            COUNT(*) as request_count
        FROM spans
        WHERE time >= $1 AND time < $2
        GROUP BY bucket, provider
        ORDER BY bucket, provider
    """,
    TrendingGroupBy.STAGE: """
        SELECT
            time_bucket($3::interval, time) as bucket,
            stage as dimension,
            COALESCE(SUM(cost_total), 0) as cost,
            COUNT(*) as request_count
        FROM spans
        WHERE time >= $1 AND time < $2
        GROUP BY bucket, stage
        ORDER BY bucket, stage
    """,
}


async def get_pipeline_cost(
    pool: asyncpg.Pool, pipeline_id: str
) -> PipelineCostResponse | None:
    """Get cost breakdown for a specific pipeline.

    Returns PipelineCostResponse or None if pipeline has no spans.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                stage,
                model,
                provider,
                SUM(tokens_input) as tokens_input,
                SUM(tokens_output) as tokens_output,
                SUM(cost_input) as cost_input,
                SUM(cost_output) as cost_output,
                SUM(cost_total) as cost_total,
                COUNT(*) as span_count,
                MIN(time) as first_seen,
                MAX(time) as last_seen
            FROM spans
            WHERE pipeline_id = $1
            GROUP BY stage, model, provider
            ORDER BY stage, model
            """,
            pipeline_id,
        )

        if not rows:
            return None

        stages: list[StageCost] = []
        total_cost: float | None = 0.0
        spans_with_cost = 0
        total_spans = 0
        first_seen = rows[0]["first_seen"]
        last_seen = rows[0]["last_seen"]

        for row in rows:
            total_spans += row["span_count"]

            stage_cost = row["cost_total"]
            if stage_cost is not None:
                spans_with_cost += row["span_count"]

            # Track overall time range across all stages
            if row["first_seen"] < first_seen:
                first_seen = row["first_seen"]
            if row["last_seen"] > last_seen:
                last_seen = row["last_seen"]

            stages.append(
                StageCost(
                    stage=row["stage"],
                    model=row["model"],
                    provider=row["provider"],
                    tokens_input=row["tokens_input"],
                    tokens_output=row["tokens_output"],
                    cost_input=row["cost_input"],
                    cost_output=row["cost_output"],
                    cost_total=row["cost_total"],
                    span_count=row["span_count"],
                )
            )

            # Accumulate total cost (null if any stage missing cost)
            if total_cost is not None:
                if stage_cost is not None:
                    total_cost += stage_cost
                else:
                    total_cost = None

        coverage_ratio = spans_with_cost / total_spans if total_spans > 0 else 0.0
        is_partial = coverage_ratio < 1.0

        return PipelineCostResponse(
            pipeline_id=pipeline_id,
            total_cost=total_cost if total_cost is not None else 0.0,
            is_partial=is_partial,
            coverage_ratio=coverage_ratio,
            stages=stages,
            first_seen=first_seen,
            last_seen=last_seen,
        )


async def list_pipelines(
    pool: asyncpg.Pool,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> PipelineListResponse:
    """List pipelines with pagination and optional time filtering."""
    async with pool.acquire() as conn:
        where_clauses: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if start:
            where_clauses.append(f"time >= ${param_idx}")
            params.append(start)
            param_idx += 1

        if end:
            where_clauses.append(f"time <= ${param_idx}")
            params.append(end)
            param_idx += 1

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_row = await conn.fetchrow(
            f"""
            SELECT COUNT(DISTINCT pipeline_id) as total
            FROM spans
            {where_sql}
            """,
            *params,
        )
        total = count_row["total"] if count_row else 0

        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT
                pipeline_id,
                MIN(time) as first_seen,
                MAX(time) as last_seen,
                COUNT(*) as span_count,
                COALESCE(SUM(cost_total), 0) as total_cost,
                COUNT(*) FILTER (WHERE cost_total IS NULL) > 0 as is_partial
            FROM spans
            {where_sql}
            GROUP BY pipeline_id
            ORDER BY last_seen DESC
            LIMIT ${param_idx}
            OFFSET ${param_idx + 1}
            """,
            *params,
        )

        pipelines = [
            PipelineSummary(
                pipeline_id=row["pipeline_id"],
                total_cost=row["total_cost"],
                is_partial=row["is_partial"],
                span_count=row["span_count"],
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
            )
            for row in rows
        ]

        return PipelineListResponse(
            pipelines=pipelines,
            total=total,
            limit=limit,
            offset=offset,
        )


async def get_trending(
    pool: asyncpg.Pool,
    start: datetime,
    end: datetime,
    interval: str,
    group_by: str,
) -> TrendingResponse:
    """Get cost trending data over time with dimensional breakdown.

    Uses time_bucket for aggregation by the requested interval and group_by dimension.

    Args:
        pool: Database connection pool
        start: Start of time range (inclusive)
        end: End of time range (exclusive)
        interval: Aggregation interval - must be 'hour', 'day', or 'week'
        group_by: Dimension to group by - must be 'model', 'provider', or 'stage'

    Returns:
        TrendingResponse with bucketed cost data

    Raises:
        ValueError: If interval or group_by values are invalid
    """
    # Validate and convert interval using enum (prevents injection)
    try:
        interval_enum = TrendingInterval(interval)
    except ValueError:
        valid_intervals = ", ".join(i.value for i in TrendingInterval)
        raise ValueError(
            f"Invalid interval: {interval}. Must be one of: {valid_intervals}"
        )

    # Validate and convert group_by using enum (prevents injection)
    try:
        group_by_enum = TrendingGroupBy(group_by)
    except ValueError:
        valid_groups = ", ".join(g.value for g in TrendingGroupBy)
        raise ValueError(
            f"Invalid group_by: {group_by}. Must be one of: {valid_groups}"
        )

    # Get the pre-built query template (no string interpolation)
    query = _TRENDING_QUERIES[group_by_enum]
    pg_interval = _INTERVAL_TO_PG[interval_enum]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            query,
            start,
            end,
            pg_interval,  # Passed as parameter, not interpolated
        )

        # Group by bucket timestamp
        buckets_dict: dict[datetime, list[dict[str, Any]]] = {}
        for row in rows:
            bucket_ts = row["bucket"]
            if bucket_ts not in buckets_dict:
                buckets_dict[bucket_ts] = []
            buckets_dict[bucket_ts].append(
                {
                    "key": row["dimension"],
                    "cost": float(row["cost"]),
                    "request_count": row["request_count"],
                }
            )

        buckets: list[TrendingBucket] = []
        for bucket_ts in sorted(buckets_dict):
            breakdowns = buckets_dict[bucket_ts]
            total_cost = sum(b["cost"] for b in breakdowns)
            total_requests = sum(b["request_count"] for b in breakdowns)
            avg_cost = total_cost / total_requests if total_requests > 0 else 0.0

            breakdown_models = [
                TrendingBucketBreakdown(
                    key=b["key"],
                    cost=b["cost"],
                    percentage=(b["cost"] / total_cost * 100.0) if total_cost > 0 else 0.0,
                )
                for b in breakdowns
            ]

            buckets.append(
                TrendingBucket(
                    timestamp=bucket_ts,
                    total_cost=total_cost,
                    request_count=total_requests,
                    avg_cost_per_request=avg_cost,
                    breakdown=breakdown_models,
                )
            )

        return TrendingResponse(buckets=buckets)
