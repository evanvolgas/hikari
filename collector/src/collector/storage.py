"""Async PostgreSQL span writer with buffering and retry logic."""

import asyncio
import logging
from collections import deque
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class SpanWriter:
    """
    Async span writer with in-memory buffering and connection retry.

    Buffers spans in memory when database is unavailable, retries connection
    periodically, and drops oldest spans when buffer is full.
    """

    # Buffer size constants with documentation
    DEFAULT_MAX_BUFFER_SIZE: int = 50_000  # ~75MB at 1.5KB/span average
    DEFAULT_RETRY_INTERVAL: float = 10.0  # seconds

    def __init__(
        self,
        max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE,
        retry_interval: float = DEFAULT_RETRY_INTERVAL,
    ):
        """
        Initialize span writer.

        Args:
            max_buffer_size: Maximum number of spans to buffer in memory.
                Default 50,000 spans (~75MB assuming 1.5KB average span size).
                When buffer is full, oldest spans are dropped.
            retry_interval: Seconds between database reconnection attempts.
                Default 10 seconds.
        """
        self._pool: asyncpg.Pool | None = None
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_buffer_size)
        self._max_buffer_size = max_buffer_size
        self._retry_interval = retry_interval
        self._retry_task: asyncio.Task[None] | None = None
        self._connected = False
        self._database_url: str = ""  # Store URL for reconnection

    @property
    def db_connected(self) -> bool:
        """Return True if database connection is active."""
        return self._connected

    @property
    def pool(self) -> asyncpg.Pool | None:
        """Return the database connection pool.

        Returns None if not connected. Use `db_connected` property to check
        connection status before accessing the pool.

        This is the public interface for accessing the pool - routes and
        queries should use this property instead of accessing _pool directly.
        """
        return self._pool

    def buffer_usage(self) -> float:
        """Return buffer usage ratio (0.0 to 1.0)."""
        return len(self._buffer) / self._max_buffer_size

    async def connect(self, database_url: str) -> None:
        """
        Create database connection pool.

        Args:
            database_url: PostgreSQL connection URL (asyncpg format or with +asyncpg)
        """
        # Strip SQLAlchemy dialect prefix if present
        url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        # Store URL for reconnection (avoids accessing private pool attributes)
        self._database_url = url

        try:
            self._pool = await asyncpg.create_pool(
                url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            self._connected = True
            logger.info("Connected to database")

            # Flush buffered spans after successful connection
            await self._flush_buffer()

        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            self._connected = False
            # Start retry background task
            if self._retry_task is None or self._retry_task.done():
                self._retry_task = asyncio.create_task(self._retry_connection(url))

    async def _retry_connection(self, database_url: str) -> None:
        """Background task to retry database connection."""
        while not self._connected:
            await asyncio.sleep(self._retry_interval)
            logger.info("Retrying database connection...")
            try:
                self._pool = await asyncpg.create_pool(
                    database_url,
                    min_size=2,
                    max_size=10,
                    command_timeout=30,
                )
                self._connected = True
                logger.info("Database connection restored")

                # Flush buffered spans
                await self._flush_buffer()

            except Exception as e:
                logger.error(f"Database reconnection failed: {e}")

    async def _flush_buffer(self) -> None:
        """Flush all buffered spans to database."""
        if not self._buffer:
            return

        spans_to_flush = list(self._buffer)
        self._buffer.clear()

        logger.info(f"Flushing {len(spans_to_flush)} buffered spans")
        await self._write_to_db(spans_to_flush)

    async def write_spans(self, spans: list[dict[str, Any]]) -> None:
        """
        Write spans to database or buffer if unavailable.

        Args:
            spans: List of span dictionaries with database columns
        """
        if self._connected and self._pool is not None:
            try:
                await self._write_to_db(spans)
            except Exception as e:
                logger.error(f"Failed to write spans to database: {e}")
                self._connected = False
                self._buffer_spans(spans)
                # Trigger reconnection using stored URL (not private pool attributes)
                if self._retry_task is None or self._retry_task.done():
                    if self._database_url:
                        self._retry_task = asyncio.create_task(
                            self._retry_connection(self._database_url)
                        )
                    else:
                        logger.error("Cannot retry connection: no database URL stored")
        else:
            self._buffer_spans(spans)

    def _buffer_spans(self, spans: list[dict[str, Any]]) -> None:
        """Add spans to in-memory buffer, dropping oldest if full."""
        initial_len = len(self._buffer)

        for span in spans:
            self._buffer.append(span)

        dropped = max(0, initial_len + len(spans) - self._max_buffer_size)
        if dropped > 0:
            logger.warning(
                f"Buffer full ({self._max_buffer_size}), dropped {dropped} oldest spans"
            )

    async def _write_to_db(self, spans: list[dict[str, Any]]) -> None:
        """
        Batch insert spans into PostgreSQL.

        Args:
            spans: List of span dictionaries
        """
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        if not spans:
            return

        # Prepare batch insert
        records = [
            (
                span.get("time"),
                span.get("trace_id"),
                span.get("span_id"),
                span.get("span_name"),
                span.get("pipeline_id"),
                span.get("stage"),
                span.get("model"),
                span.get("provider"),
                span.get("tokens_input"),
                span.get("tokens_output"),
                span.get("cost_input"),
                span.get("cost_output"),
                span.get("cost_total"),
                span.get("duration_ms"),
            )
            for span in spans
        ]

        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO spans (
                    time, trace_id, span_id, span_name, pipeline_id,
                    stage, model, provider, tokens_input, tokens_output,
                    cost_input, cost_output, cost_total, duration_ms
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (time, span_id) DO NOTHING
                """,
                records,
            )

        logger.info(f"Wrote {len(spans)} spans to database")

    async def close(self) -> None:
        """Close database connection pool and cancel retry task."""
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass

        if self._pool:
            await self._pool.close()
            logger.info("Database connection closed")
