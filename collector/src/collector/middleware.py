"""Middleware components for Hikari Collector API.

Includes rate limiting to protect against abuse and ensure fair resource usage.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Callable

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """Token bucket rate limiter for API endpoints.

    The token bucket algorithm allows for burst traffic while maintaining
    a long-term average rate. Tokens are added at a constant rate up to
    a maximum bucket size, and each request consumes one token.

    This implementation is in-memory and per-process. For production
    deployments with multiple collector instances, consider using Redis
    or another distributed rate limiting solution.

    Attributes:
        rate: Tokens added per second (sustained request rate)
        burst: Maximum bucket size (burst capacity)
    """

    def __init__(self, rate: float = 100.0, burst: int = 200):
        """Initialize the rate limiter.

        Args:
            rate: Tokens added per second. Default 100 requests/second sustained.
            burst: Maximum tokens in bucket (burst capacity). Default 200 requests.

        Example:
            With rate=100 and burst=200, a client can:
            - Burst up to 200 requests instantly
            - Then sustain 100 requests/second
        """
        self.rate = rate
        self.burst = burst
        # Per-client state: {client_id: (tokens, last_update_time)}
        self._buckets: dict[str, tuple[float, float]] = defaultdict(
            lambda: (float(burst), time.monotonic())
        )

    def _get_client_id(self, request: Request) -> str:
        """Extract client identifier from request.

        Uses X-Forwarded-For header if present (for clients behind proxies),
        otherwise falls back to direct client IP.

        Args:
            request: The incoming request

        Returns:
            String identifier for the client
        """
        # Check for forwarded header (common in reverse proxy setups)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first IP in the chain (original client)
            return forwarded.split(",")[0].strip()

        # Fall back to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def is_allowed(self, request: Request) -> tuple[bool, dict[str, str]]:
        """Check if a request should be allowed.

        Updates the token bucket for the client and returns whether the
        request should proceed.

        Args:
            request: The incoming request

        Returns:
            Tuple of (allowed: bool, headers: dict) where headers contains
            rate limit information to include in the response.
        """
        client_id = self._get_client_id(request)
        now = time.monotonic()

        # Get current bucket state
        tokens, last_update = self._buckets[client_id]

        # Add tokens based on time elapsed
        elapsed = now - last_update
        tokens = min(self.burst, tokens + elapsed * self.rate)

        # Build response headers
        headers = {
            "X-RateLimit-Limit": str(self.burst),
            "X-RateLimit-Remaining": str(max(0, int(tokens) - 1)),
            "X-RateLimit-Reset": str(int(now + (self.burst - tokens) / self.rate)),
        }

        # Check if we have tokens available
        if tokens >= 1.0:
            # Consume a token
            self._buckets[client_id] = (tokens - 1.0, now)
            return True, headers
        else:
            # No tokens available
            self._buckets[client_id] = (tokens, now)
            # Calculate retry time
            retry_after = int((1.0 - tokens) / self.rate) + 1
            headers["Retry-After"] = str(retry_after)
            return False, headers

    def cleanup_stale_buckets(self, max_age_seconds: float = 3600.0) -> int:
        """Remove stale client buckets to prevent memory growth.

        Args:
            max_age_seconds: Remove buckets not updated in this many seconds

        Returns:
            Number of buckets removed
        """
        now = time.monotonic()
        stale_clients = [
            client_id
            for client_id, (_, last_update) in self._buckets.items()
            if now - last_update > max_age_seconds
        ]
        for client_id in stale_clients:
            del self._buckets[client_id]
        return len(stale_clients)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting requests.

    Applies token bucket rate limiting to protect the ingestion endpoint
    from abuse while allowing legitimate burst traffic.

    Rate limiting is only applied to the POST /v1/traces endpoint by default,
    as this is the high-volume ingestion path. Read endpoints (GET) are not
    rate limited to allow monitoring tools to query freely.
    """

    # Endpoints to rate limit (by path prefix and method)
    RATE_LIMITED_ENDPOINTS = {
        ("POST", "/v1/traces"),  # Span ingestion
    }

    def __init__(
        self,
        app,
        rate: float = 100.0,
        burst: int = 200,
        enabled: bool = True,
    ):
        """Initialize rate limiting middleware.

        Args:
            app: The FastAPI application
            rate: Sustained requests per second allowed (default 100)
            burst: Maximum burst size (default 200)
            enabled: Whether rate limiting is active (default True)
        """
        super().__init__(app)
        self.limiter = TokenBucketRateLimiter(rate=rate, burst=burst)
        self.enabled = enabled
        logger.info(
            f"Rate limiting {'enabled' if enabled else 'disabled'}: "
            f"{rate} req/s sustained, {burst} burst capacity"
        )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request through rate limiter.

        Args:
            request: The incoming request
            call_next: Next handler in the middleware chain

        Returns:
            Response from the handler or 429 if rate limited
        """
        # Skip if rate limiting is disabled
        if not self.enabled:
            return await call_next(request)

        # Check if this endpoint should be rate limited
        endpoint_key = (request.method, request.url.path)
        if endpoint_key not in self.RATE_LIMITED_ENDPOINTS:
            return await call_next(request)

        # Apply rate limiting
        allowed, headers = self.limiter.is_allowed(request)

        if allowed:
            response = await call_next(request)
            # Add rate limit headers to successful responses
            for key, value in headers.items():
                response.headers[key] = value
            return response
        else:
            # Rate limited - return 429 with retry information
            client_id = self.limiter._get_client_id(request)
            logger.warning(f"Rate limit exceeded for client: {client_id}")

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please reduce request frequency.",
                headers=headers,
            )
