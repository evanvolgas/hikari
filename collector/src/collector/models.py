"""Pydantic models for Hikari Collector API and OTLP ingestion."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator
from pydantic.functional_validators import AfterValidator


# Validation constants
PIPELINE_ID_MAX_LENGTH = 256
PIPELINE_ID_MIN_LENGTH = 1
SPAN_ID_MAX_LENGTH = 64
TRACE_ID_MAX_LENGTH = 64

# Valid characters: alphanumeric, hyphens, underscores, colons, periods
# This matches common trace ID formats (hex, UUID, custom identifiers)
_PIPELINE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9\-_:.]+$")


def validate_pipeline_id(value: str) -> str:
    """Validate pipeline_id format and length.

    Args:
        value: The pipeline ID to validate

    Returns:
        The validated pipeline ID

    Raises:
        ValueError: If validation fails
    """
    if not value or len(value) < PIPELINE_ID_MIN_LENGTH:
        raise ValueError(
            f"pipeline_id must be at least {PIPELINE_ID_MIN_LENGTH} character(s)"
        )
    if len(value) > PIPELINE_ID_MAX_LENGTH:
        raise ValueError(
            f"pipeline_id must not exceed {PIPELINE_ID_MAX_LENGTH} characters"
        )
    if not _PIPELINE_ID_PATTERN.match(value):
        raise ValueError(
            "pipeline_id must contain only alphanumeric characters, "
            "hyphens, underscores, colons, and periods"
        )
    return value


# Annotated type for validated pipeline IDs
ValidatedPipelineId = Annotated[str, AfterValidator(validate_pipeline_id)]


# OTLP Ingestion Models


class SpanAttribute(BaseModel):
    key: str
    value: Any  # {"stringValue": ...} | {"intValue": ...} | {"doubleValue": ...}


class Span(BaseModel):
    traceId: str = Field(..., min_length=1, max_length=TRACE_ID_MAX_LENGTH)
    spanId: str = Field(..., min_length=1, max_length=SPAN_ID_MAX_LENGTH)
    name: str = Field(..., min_length=1, max_length=256)
    startTimeUnixNano: str
    endTimeUnixNano: str
    attributes: list[SpanAttribute] = Field(default_factory=list)

    @field_validator("traceId", "spanId")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        """Validate trace/span ID contains only safe characters.

        Allows alphanumeric characters, hyphens, and underscores.
        This is more permissive than strict hex to accommodate various
        ID formats in test and production environments.
        """
        if not re.match(r"^[a-zA-Z0-9\-_]+$", v):
            raise ValueError(
                "ID must contain only alphanumeric characters, hyphens, and underscores"
            )
        return v


class ScopeSpans(BaseModel):
    spans: list[Span] = Field(default_factory=list)


class ResourceSpans(BaseModel):
    scopeSpans: list[ScopeSpans] = Field(default_factory=list)


class IngestRequest(BaseModel):
    resourceSpans: list[ResourceSpans]


class IngestResponse(BaseModel):
    accepted: int
    rejected: int = 0
    errors: list[str] = Field(default_factory=list)


# Pipeline Cost Models


class StageCost(BaseModel):
    stage: str
    model: str
    provider: str
    tokens_input: int | None
    tokens_output: int | None
    cost_input: float | None = None
    cost_output: float | None = None
    cost_total: float | None = None
    span_count: int


class PipelineCostResponse(BaseModel):
    pipeline_id: ValidatedPipelineId
    total_cost: float = Field(..., ge=0.0)
    is_partial: bool
    coverage_ratio: float = Field(..., ge=0.0, le=1.0)
    stages: list[StageCost] = Field(default_factory=list)
    first_seen: datetime
    last_seen: datetime


class PipelineSummary(BaseModel):
    pipeline_id: ValidatedPipelineId
    total_cost: float = Field(..., ge=0.0)
    is_partial: bool
    span_count: int = Field(..., ge=0)
    first_seen: datetime
    last_seen: datetime


class PipelineListResponse(BaseModel):
    pipelines: list[PipelineSummary]
    total: int
    limit: int
    offset: int


# Trending Models


class TrendingBucketBreakdown(BaseModel):
    key: str
    cost: float
    percentage: float


class TrendingBucket(BaseModel):
    timestamp: datetime
    total_cost: float
    request_count: int
    avg_cost_per_request: float
    breakdown: list[TrendingBucketBreakdown]


class TrendingResponse(BaseModel):
    buckets: list[TrendingBucket]


# Health Check


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    db_connected: bool
    buffer_usage: float
    version: str
