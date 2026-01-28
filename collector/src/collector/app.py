"""FastAPI application for Hikari Collector."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from collector.config import Settings
from collector.middleware import RateLimitMiddleware
from collector.routes import router
from collector.storage import SpanWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional settings instance. If not provided, loads from environment.

    Returns:
        Configured FastAPI application instance.
    """
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan manager for startup and shutdown."""
        # Startup
        writer = SpanWriter(
            max_buffer_size=settings.buffer_max_size,
            retry_interval=settings.db_retry_interval_seconds,
        )

        await writer.connect(settings.database_url)

        # Store in app state
        app.state.writer = writer
        app.state.version = "0.1.0"
        app.state.settings = settings

        logger.info("Hikari Collector started")

        yield

        # Shutdown
        await writer.close()
        logger.info("Hikari Collector stopped")

    application = FastAPI(
        title="Hikari Collector",
        description="OpenTelemetry-based LLM pipeline cost intelligence",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Add rate limiting middleware
    application.add_middleware(
        RateLimitMiddleware,
        rate=settings.rate_limit_requests_per_second,
        burst=settings.rate_limit_burst_size,
        enabled=settings.rate_limit_enabled,
    )

    application.include_router(router)

    return application


# Default application instance for uvicorn
app = create_app()
