"""
Caching Middleware for FastAPI.

Provides enterprise-grade caching with:
- In-memory caching
- Redis backend support
- Cache invalidation strategies
- TTL configuration
- Cache key generation
"""

import hashlib
import json
import time
from typing import Any, Callable, Dict, Optional, Tuple

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class InMemoryCache:
    """
    Simple in-memory cache with TTL support.

    Example:
        ```python
        from fastapi.middleware.cache import InMemoryCache

        cache = InMemoryCache()
        cache.set("key", "value", ttl=60)
        value = cache.get("key")
        ```
    """

    def __init__(self) -> None:
        self.cache: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if key not in self.cache:
            return None

        value, expires_at = self.cache[key]
        if expires_at > 0 and time.time() > expires_at:
            # Expired
            del self.cache[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: int = 0) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (0 = no expiration)
        """
        expires_at = time.time() + ttl if ttl > 0 else 0
        self.cache[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        """Delete value from cache."""
        if key in self.cache:
            del self.cache[key]

    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()

    def size(self) -> int:
        """Get number of cached items."""
        return len(self.cache)


class RedisCache:
    """
    Redis-backed cache.

    Example:
        ```python
        from fastapi.middleware.cache import RedisCache
        import redis

        redis_client = redis.Redis(host='localhost', port=6379, db=0)
        cache = RedisCache(redis_client)
        cache.set("key", "value", ttl=60)
        value = cache.get("key")
        ```
    """

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    def get(self, key: str) -> Optional[str]:
        """Get value from Redis cache."""
        try:
            value = self.redis.get(key)
            return value.decode() if value else None
        except Exception:
            return None

    def set(self, key: str, value: str, ttl: int = 0) -> None:
        """
        Set value in Redis cache.

        Args:
            key: Cache key
            value: Value to cache (string)
            ttl: Time to live in seconds (0 = no expiration)
        """
        try:
            if ttl > 0:
                self.redis.setex(key, ttl, value)
            else:
                self.redis.set(key, value)
        except Exception:
            pass  # Don't fail request if cache fails

    def delete(self, key: str) -> None:
        """Delete value from Redis cache."""
        try:
            self.redis.delete(key)
        except Exception:
            pass

    def clear(self) -> None:
        """Clear all cache entries (use with caution!)."""
        try:
            self.redis.flushdb()
        except Exception:
            pass


class CacheMiddleware:
    """
    HTTP caching middleware for FastAPI.

    Caches GET request responses based on URL and query parameters.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.cache import CacheMiddleware

        app = FastAPI()
        app.add_middleware(
            CacheMiddleware,
            default_ttl=60,
            cache_paths=["/api/data"],
        )
        ```

    Args:
        app: The ASGI application
        backend: Cache backend (InMemoryCache or RedisCache)
        default_ttl: Default TTL in seconds
        cache_paths: Paths to cache (None = cache all GET requests)
        exclude_paths: Paths to exclude from caching
        cache_key_generator: Custom cache key generator function
        cache_status_codes: HTTP status codes to cache
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        backend: Optional[Any] = None,
        default_ttl: int = 60,
        cache_paths: Optional[list] = None,
        exclude_paths: Optional[list] = None,
        cache_key_generator: Optional[Callable[[Scope], str]] = None,
        cache_status_codes: Optional[list] = None,
    ) -> None:
        self.app = app
        self.backend = backend or InMemoryCache()
        self.default_ttl = default_ttl
        self.cache_paths = cache_paths
        self.exclude_paths = set(exclude_paths or ["/health", "/metrics"])
        self.cache_key_generator = cache_key_generator or self._default_key_generator
        self.cache_status_codes = set(cache_status_codes or [200])

    def _default_key_generator(self, scope: Scope) -> str:
        """Generate cache key from request."""
        method = scope.get("method", "")
        path = scope.get("path", "")
        query_string = scope.get("query_string", b"").decode()

        # Create unique key from method, path, and query
        key_parts = [method, path]
        if query_string:
            key_parts.append(query_string)

        key_string = ":".join(key_parts)
        # Hash to keep key size reasonable
        return hashlib.md5(key_string.encode()).hexdigest()

    def _should_cache(self, scope: Scope) -> bool:
        """Check if request should be cached."""
        method = scope.get("method", "")
        path = scope.get("path", "")

        # Only cache GET requests
        if method != "GET":
            return False

        # Check excluded paths
        if path in self.exclude_paths:
            return False

        # Check cache paths
        if self.cache_paths:
            return any(path.startswith(prefix) for prefix in self.cache_paths)

        return True

    def _get_ttl(self, headers: Dict) -> int:
        """Extract TTL from Cache-Control header."""
        cache_control = headers.get(b"cache-control", b"").decode()
        if "max-age=" in cache_control:
            try:
                max_age = cache_control.split("max-age=")[1].split(",")[0]
                return int(max_age)
            except (IndexError, ValueError):
                pass
        return self.default_ttl

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._should_cache(scope):
            await self.app(scope, receive, send)
            return

        # Generate cache key
        cache_key = self.cache_key_generator(scope)

        # Try to get from cache
        cached_response = self.backend.get(cache_key)
        if cached_response:
            # Return cached response
            try:
                response_data = json.loads(cached_response)
                headers = [
                    (k.encode(), v.encode())
                    for k, v in response_data.get("headers", {}).items()
                ]
                headers.append((b"x-cache", b"HIT"))

                await send({
                    "type": "http.response.start",
                    "status": response_data.get("status", 200),
                    "headers": headers,
                })
                await send({
                    "type": "http.response.body",
                    "body": response_data.get("body", "").encode(),
                })
                return
            except Exception:
                # If cache is corrupted, continue to backend
                pass

        # Cache miss - call backend and cache response
        status_code = 200
        response_headers = {}
        response_body = b""

        async def send_with_caching(message: Message) -> None:
            nonlocal status_code, response_headers, response_body

            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                response_headers = dict(message.get("headers", []))

                # Add cache miss header
                response_headers[b"x-cache"] = b"MISS"
                message["headers"] = list(response_headers.items())

            elif message["type"] == "http.response.body":
                response_body = message.get("body", b"")

                # Cache response if status code is cacheable
                if status_code in self.cache_status_codes:
                    ttl = self._get_ttl(response_headers)

                    cache_data = {
                        "status": status_code,
                        "headers": {
                            k.decode(): v.decode()
                            for k, v in response_headers.items()
                            if k not in [b"x-cache", b"set-cookie"]
                        },
                        "body": response_body.decode(errors="ignore"),
                    }

                    try:
                        self.backend.set(cache_key, json.dumps(cache_data), ttl=ttl)
                    except Exception:
                        pass  # Don't fail request if caching fails

            await send(message)

        await self.app(scope, receive, send_with_caching)


class CacheControlMiddleware:
    """
    Middleware to add Cache-Control headers to responses.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.cache import CacheControlMiddleware

        app = FastAPI()
        app.add_middleware(
            CacheControlMiddleware,
            default_max_age=60,
        )
        ```

    Args:
        app: The ASGI application
        default_max_age: Default max-age in seconds
        public: Whether cache is public or private
        must_revalidate: Whether cache must revalidate
        no_store_paths: Paths that should not be cached
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_max_age: int = 60,
        public: bool = True,
        must_revalidate: bool = False,
        no_store_paths: Optional[list] = None,
    ) -> None:
        self.app = app
        self.default_max_age = default_max_age
        self.public = public
        self.must_revalidate = must_revalidate
        self.no_store_paths = set(no_store_paths or [])

    def _should_no_store(self, path: str) -> bool:
        """Check if path should have no-store directive."""
        return path in self.no_store_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        async def send_with_cache_control(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))

                # Only add Cache-Control for GET requests
                if method == "GET" and b"cache-control" not in headers:
                    if self._should_no_store(path):
                        cache_control = "no-store, no-cache, must-revalidate"
                    else:
                        parts = []
                        if self.public:
                            parts.append("public")
                        else:
                            parts.append("private")

                        parts.append(f"max-age={self.default_max_age}")

                        if self.must_revalidate:
                            parts.append("must-revalidate")

                        cache_control = ", ".join(parts)

                    headers[b"cache-control"] = cache_control.encode()
                    message["headers"] = list(headers.items())

            await send(message)

        await self.app(scope, receive, send_with_cache_control)
