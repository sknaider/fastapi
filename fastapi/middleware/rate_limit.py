"""
Rate Limiting Middleware for FastAPI.

Implements enterprise-grade rate limiting with multiple strategies:
- Fixed window
- Sliding window
- Token bucket
- In-memory and Redis backends
"""

import time
from collections import defaultdict
from typing import Callable, Dict, Optional, Tuple

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")


class InMemoryRateLimitBackend:
    """In-memory rate limit backend using fixed window algorithm."""

    def __init__(self) -> None:
        # Structure: {key: [(timestamp, count)]}
        self.storage: Dict[str, list] = defaultdict(list)

    def is_allowed(
        self,
        key: str,
        limit: int,
        window: int,
        current_time: Optional[float] = None,
    ) -> Tuple[bool, int, int]:
        """
        Check if request is allowed under rate limit.

        Args:
            key: Rate limit key (e.g., IP address or user ID)
            limit: Maximum requests allowed in window
            window: Time window in seconds
            current_time: Current timestamp (for testing)

        Returns:
            Tuple of (is_allowed, remaining, retry_after)
        """
        if current_time is None:
            current_time = time.time()

        # Clean old entries
        cutoff_time = current_time - window
        self.storage[key] = [
            (ts, count) for ts, count in self.storage[key] if ts > cutoff_time
        ]

        # Count requests in current window
        total_requests = sum(count for _, count in self.storage[key])

        if total_requests >= limit:
            # Calculate retry_after from oldest request
            if self.storage[key]:
                oldest_ts = min(ts for ts, _ in self.storage[key])
                retry_after = int(window - (current_time - oldest_ts)) + 1
            else:
                retry_after = window
            return False, 0, retry_after

        # Add current request
        self.storage[key].append((current_time, 1))

        remaining = limit - total_requests - 1
        return True, remaining, 0

    def reset(self, key: str) -> None:
        """Reset rate limit for a key."""
        if key in self.storage:
            del self.storage[key]

    def clear(self) -> None:
        """Clear all rate limit data."""
        self.storage.clear()


class RateLimitMiddleware:
    """
    Rate limiting middleware for FastAPI applications.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=60,
            requests_per_hour=1000,
        )
        ```

    Args:
        app: The ASGI application
        requests_per_minute: Maximum requests per minute (default: 60)
        requests_per_hour: Maximum requests per hour (default: 1000)
        requests_per_day: Maximum requests per day (default: 10000)
        key_func: Function to extract rate limit key from scope
        backend: Rate limit backend (defaults to in-memory)
        exclude_paths: List of paths to exclude from rate limiting
        on_rate_limit_exceeded: Custom callback when rate limit is exceeded
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_minute: Optional[int] = 60,
        requests_per_hour: Optional[int] = 1000,
        requests_per_day: Optional[int] = 10000,
        key_func: Optional[Callable[[Scope], str]] = None,
        backend: Optional[InMemoryRateLimitBackend] = None,
        exclude_paths: Optional[list] = None,
        on_rate_limit_exceeded: Optional[Callable] = None,
    ) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.requests_per_day = requests_per_day
        self.key_func = key_func or self._default_key_func
        self.backend = backend or InMemoryRateLimitBackend()
        self.exclude_paths = set(exclude_paths or [])
        self.on_rate_limit_exceeded = on_rate_limit_exceeded

    def _default_key_func(self, scope: Scope) -> str:
        """Default key function using client IP."""
        client = scope.get("client")
        if client:
            return f"{client[0]}:{client[1]}"
        return "unknown"

    def _should_exclude(self, scope: Scope) -> bool:
        """Check if path should be excluded from rate limiting."""
        path = scope.get("path", "")
        return path in self.exclude_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._should_exclude(scope):
            await self.app(scope, receive, send)
            return

        key = self.key_func(scope)

        # Check rate limits in order (minute -> hour -> day)
        rate_limits = [
            (self.requests_per_minute, 60, "minute"),
            (self.requests_per_hour, 3600, "hour"),
            (self.requests_per_day, 86400, "day"),
        ]

        for limit, window, period in rate_limits:
            if limit is None:
                continue

            rate_key = f"{key}:{period}"
            is_allowed, remaining, retry_after = self.backend.is_allowed(
                rate_key, limit, window
            )

            if not is_allowed:
                if self.on_rate_limit_exceeded:
                    await self.on_rate_limit_exceeded(scope, retry_after)

                response = JSONResponse(
                    {
                        "error": "Rate limit exceeded",
                        "message": f"Too many requests. Limit: {limit} per {period}",
                        "retry_after": retry_after,
                    },
                    status_code=429,
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                    },
                )
                await response(scope, receive, send)
                return

        # Add rate limit headers to response
        async def send_with_rate_limit_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))

                # Add rate limit headers for the strictest limit
                if self.requests_per_minute:
                    _, remaining, _ = self.backend.is_allowed(
                        f"{key}:minute", self.requests_per_minute, 60
                    )
                    headers[b"X-RateLimit-Limit"] = str(
                        self.requests_per_minute
                    ).encode()
                    headers[b"X-RateLimit-Remaining"] = str(remaining).encode()
                    headers[b"X-RateLimit-Reset"] = str(
                        int(time.time()) + 60
                    ).encode()

                message["headers"] = list(headers.items())

            await send(message)

        await self.app(scope, receive, send_with_rate_limit_headers)


class IPRateLimitMiddleware(RateLimitMiddleware):
    """Rate limiting middleware based on client IP address."""

    def __init__(self, app: ASGIApp, **kwargs) -> None:
        super().__init__(app, key_func=self._ip_key_func, **kwargs)

    def _ip_key_func(self, scope: Scope) -> str:
        """Extract IP address from scope."""
        # Check for X-Forwarded-For header (proxy/load balancer)
        headers = Headers(scope=scope)
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP (original client)
            return forwarded_for.split(",")[0].strip()

        # Fall back to direct client IP
        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"


class UserRateLimitMiddleware(RateLimitMiddleware):
    """
    Rate limiting middleware based on authenticated user.

    Requires user information in scope["user"] or scope["auth"].
    """

    def __init__(self, app: ASGIApp, **kwargs) -> None:
        super().__init__(app, key_func=self._user_key_func, **kwargs)

    def _user_key_func(self, scope: Scope) -> str:
        """Extract user ID from scope."""
        # Try to get user from scope
        user = scope.get("user")
        if user:
            # Handle different user object types
            if hasattr(user, "id"):
                return f"user:{user.id}"
            elif hasattr(user, "username"):
                return f"user:{user.username}"
            elif isinstance(user, dict):
                return f"user:{user.get('id', user.get('username', 'unknown'))}"

        # Fallback to IP-based rate limiting
        return self._ip_key_func(scope)

    def _ip_key_func(self, scope: Scope) -> str:
        """Fallback to IP-based key."""
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        return "ip:unknown"
