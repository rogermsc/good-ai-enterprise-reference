"""
Rate limiting using Redis with sliding window algorithm.

Provides:
- Per-user and per-tenant rate limiting
- Sliding window counter algorithm
- FastAPI middleware for automatic enforcement
- Configurable limits and windows
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from redis import asyncio as aioredis

from src.core.config import get_settings
from src.core.observability import get_logger, get_meter

logger = get_logger()
meter = get_meter()

# Rate limit metrics
rate_limit_hits = meter.create_counter(
    name="rate_limit.hits",
    description="Number of rate limit hits",
    unit="1",
)

rate_limit_exceeded = meter.create_counter(
    name="rate_limit.exceeded",
    description="Number of rate limit exceeded events",
    unit="1",
)


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime
    retry_after: int | None = None


class RateLimiter:
    """
    Rate limiter using Redis sliding window counters.

    Implements a sliding window algorithm that provides smooth rate limiting
    without the sudden reset of fixed windows.

    Example:
        limiter = RateLimiter(redis_url="redis://localhost:6379")
        await limiter.connect()

        # Check if request is allowed
        result = await limiter.check("user:123", limit=100, window_seconds=60)
        if not result.allowed:
            raise HTTPException(429, "Too many requests")

        # Or use the hit method which increments and checks
        result = await limiter.hit("user:123", limit=100, window_seconds=60)
    """

    def __init__(
        self,
        redis_url: str | None = None,
        key_prefix: str = "ratelimit",
    ):
        """
        Initialize rate limiter.

        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for Redis keys
        """
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.key_prefix = key_prefix
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        if self._redis is None:
            self._redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info("rate_limiter_connected", url=self._mask_url(self.redis_url))

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("rate_limiter_disconnected")

    def _mask_url(self, url: str) -> str:
        """Mask password in URL for logging."""
        if "@" in url:
            parts = url.split("@")
            return f"***@{parts[-1]}"
        return url

    async def hit(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitResult:
        """
        Record a hit and check if rate limit is exceeded.

        Uses sliding window counter algorithm.

        Args:
            key: Identifier (e.g., user_id, tenant_id, IP)
            limit: Maximum requests allowed in window
            window_seconds: Window size in seconds

        Returns:
            RateLimitResult with allowed status and metadata
        """
        if self._redis is None:
            # No Redis - allow all requests (log warning)
            logger.warning("rate_limiter_not_connected", key=key)
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_at=datetime.now(UTC),
            )

        now = datetime.now(UTC)
        now_ts = int(now.timestamp())
        window_start = now_ts - window_seconds

        redis_key = f"{self.key_prefix}:{key}"

        # Use Redis transaction for atomic operations
        async with self._redis.pipeline(transaction=True) as pipe:
            # Remove old entries outside the window
            pipe.zremrangebyscore(redis_key, 0, window_start)

            # Add current request with timestamp as score
            pipe.zadd(redis_key, {f"{now_ts}:{now.microsecond}": now_ts})

            # Count requests in window
            pipe.zcard(redis_key)

            # Set expiry on key
            pipe.expire(redis_key, window_seconds + 1)

            results = await pipe.execute()

        current_count = results[2]

        # Calculate remaining requests
        remaining = max(0, limit - current_count)

        # Calculate reset time
        reset_at = datetime.fromtimestamp(now_ts + window_seconds, tz=UTC)

        # Record metrics
        rate_limit_hits.add(1, {"key_type": key.split(":")[0] if ":" in key else "unknown"})

        if current_count > limit:
            rate_limit_exceeded.add(1, {"key_type": key.split(":")[0] if ":" in key else "unknown"})

            retry_after = window_seconds - (now_ts - window_start) % window_seconds

            logger.warning(
                "rate_limit_exceeded",
                key=key,
                current=current_count,
                limit=limit,
                retry_after=retry_after,
            )

            return RateLimitResult(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=reset_at,
                retry_after=retry_after,
            )

        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
        )

    async def check(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitResult:
        """
        Check rate limit without incrementing counter.

        Args:
            key: Identifier
            limit: Maximum requests allowed
            window_seconds: Window size

        Returns:
            RateLimitResult with current status
        """
        if self._redis is None:
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_at=datetime.now(UTC),
            )

        now_ts = int(datetime.now(UTC).timestamp())
        window_start = now_ts - window_seconds
        redis_key = f"{self.key_prefix}:{key}"

        # Count requests in current window
        current_count = await self._redis.zcount(redis_key, window_start, now_ts)
        remaining = max(0, limit - current_count)

        reset_at = datetime.fromtimestamp(now_ts + window_seconds, tz=UTC)

        return RateLimitResult(
            allowed=current_count < limit,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
        )

    async def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        if self._redis:
            redis_key = f"{self.key_prefix}:{key}"
            await self._redis.delete(redis_key)
            logger.info("rate_limit_reset", key=key)


# Global rate limiter instance
_rate_limiter: RateLimiter | None = None


async def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
        try:
            await _rate_limiter.connect()
        except Exception as e:
            logger.warning("rate_limiter_connection_failed", error=str(e))
    return _rate_limiter


class RateLimitMiddleware:
    """
    FastAPI middleware for rate limiting.

    Applies rate limits based on user ID, tenant ID, or IP address.

    Example:
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=100,
            burst_limit=20,
        )
    """

    def __init__(
        self,
        app: Any,
        requests_per_minute: int = 100,
        burst_limit: int = 20,
        key_func: Any | None = None,
    ):
        """
        Initialize middleware.

        Args:
            app: FastAPI application
            requests_per_minute: Rate limit per minute
            burst_limit: Short-term burst limit (per 10 seconds)
            key_func: Custom function to extract rate limit key from request
        """
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.key_func = key_func or self._default_key_func

    def _default_key_func(self, request: Request) -> str:
        """Extract rate limit key from request."""
        # Try to get user ID from headers or JWT
        user_id = request.headers.get("X-User-Id")
        tenant_id = request.headers.get("X-Tenant-Id")

        if user_id and tenant_id:
            return f"user:{tenant_id}:{user_id}"
        elif tenant_id:
            return f"tenant:{tenant_id}"
        else:
            # Fall back to IP address
            client_ip = request.client.host if request.client else "unknown"
            return f"ip:{client_ip}"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Process request through middleware."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # Skip rate limiting for health check
        if request.url.path in ("/health", "/health/ready", "/health/live"):
            await self.app(scope, receive, send)
            return

        try:
            limiter = await get_rate_limiter()
            key = self.key_func(request)

            # Check burst limit (10 second window)
            burst_result = await limiter.hit(
                f"burst:{key}",
                limit=self.burst_limit,
                window_seconds=10,
            )

            if not burst_result.allowed:
                await self._send_rate_limit_response(
                    send,
                    burst_result,
                    "Burst limit exceeded",
                )
                return

            # Check per-minute limit
            result = await limiter.hit(
                f"minute:{key}",
                limit=self.requests_per_minute,
                window_seconds=60,
            )

            if not result.allowed:
                await self._send_rate_limit_response(
                    send,
                    result,
                    "Rate limit exceeded",
                )
                return

            # Add rate limit headers to response
            async def send_with_headers(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.extend(
                        [
                            (b"X-RateLimit-Limit", str(result.limit).encode()),
                            (b"X-RateLimit-Remaining", str(result.remaining).encode()),
                            (b"X-RateLimit-Reset", str(int(result.reset_at.timestamp())).encode()),
                        ]
                    )
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_with_headers)

        except Exception as e:
            logger.error("rate_limit_middleware_error", error=str(e))
            # On error, allow request through
            await self.app(scope, receive, send)

    async def _send_rate_limit_response(
        self,
        send: Any,
        result: RateLimitResult,
        message: str,
    ) -> None:
        """Send 429 rate limit response."""
        import json

        body = json.dumps(
            {
                "detail": message,
                "retry_after": result.retry_after,
            }
        ).encode()

        headers = [
            (b"content-type", b"application/json"),
            (b"X-RateLimit-Limit", str(result.limit).encode()),
            (b"X-RateLimit-Remaining", b"0"),
            (b"X-RateLimit-Reset", str(int(result.reset_at.timestamp())).encode()),
        ]

        if result.retry_after:
            headers.append((b"Retry-After", str(result.retry_after).encode()))

        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
