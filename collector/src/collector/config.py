"""Configuration management for Hikari Collector."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden via environment variables with the HIKARI_ prefix.
    For example, HIKARI_DATABASE_URL, HIKARI_RATE_LIMIT_ENABLED, etc.
    """

    # Database settings
    database_url: str = Field(
        default="postgresql+asyncpg://hikari:hikari@localhost:5432/hikari",
        description="PostgreSQL connection URL (asyncpg format)",
    )
    buffer_max_size: int = Field(
        default=50_000,
        ge=1000,
        le=1_000_000,
        description="Maximum spans to buffer in memory when DB unavailable",
    )
    db_retry_interval_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=300.0,
        description="Seconds between database reconnection attempts",
    )
    retention_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Days to retain span data before automatic deletion",
    )

    # Server settings
    host: str = Field(
        default="0.0.0.0",
        description="Host address to bind to",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port to listen on",
    )

    # Rate limiting settings
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable rate limiting on ingestion endpoint",
    )
    rate_limit_requests_per_second: float = Field(
        default=100.0,
        ge=1.0,
        le=10000.0,
        description="Sustained requests per second allowed per client",
    )
    rate_limit_burst_size: int = Field(
        default=200,
        ge=10,
        le=10000,
        description="Maximum burst capacity per client",
    )

    model_config = {"env_prefix": "HIKARI_"}
