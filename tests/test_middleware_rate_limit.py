"""Tests for RateLimitMiddleware."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi.middleware.rate_limit import (
    InMemoryRateLimitBackend,
    RateLimitMiddleware,
)


def test_in_memory_backend():
    """Test in-memory rate limit backend."""
    backend = InMemoryRateLimitBackend()

    # First 5 requests should be allowed
    for i in range(5):
        is_allowed, remaining, retry_after = backend.is_allowed("test_key", 5, 60)
        assert is_allowed
        assert remaining == 4 - i

    # 6th request should be denied
    is_allowed, remaining, retry_after = backend.is_allowed("test_key", 5, 60)
    assert not is_allowed
    assert remaining == 0
    assert retry_after > 0


def test_rate_limit_middleware():
    """Test rate limit middleware."""
    app = FastAPI()

    backend = InMemoryRateLimitBackend()
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=5,
        backend=backend,
    )

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)

    # First 5 requests should succeed
    for i in range(5):
        response = client.get("/")
        assert response.status_code == 200
        assert "x-ratelimit-limit" in response.headers
        assert "x-ratelimit-remaining" in response.headers

    # 6th request should be rate limited
    response = client.get("/")
    assert response.status_code == 429
    assert "retry-after" in response.headers
    assert response.json()["error"] == "Rate limit exceeded"


def test_rate_limit_per_hour():
    """Test rate limit per hour."""
    app = FastAPI()

    backend = InMemoryRateLimitBackend()
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=None,
        requests_per_hour=10,
        backend=backend,
    )

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)

    # First 10 requests should succeed
    for i in range(10):
        response = client.get("/")
        assert response.status_code == 200

    # 11th request should be rate limited
    response = client.get("/")
    assert response.status_code == 429


def test_exclude_paths():
    """Test excluding paths from rate limiting."""
    app = FastAPI()

    backend = InMemoryRateLimitBackend()
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=2,
        backend=backend,
        exclude_paths=["/health"],
    )

    @app.get("/")
    def root():
        return {"message": "Hello"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(app)

    # Exhaust rate limit on /
    for i in range(2):
        response = client.get("/")
        assert response.status_code == 200

    # / should be rate limited
    response = client.get("/")
    assert response.status_code == 429

    # But /health should not be rate limited
    for i in range(10):
        response = client.get("/health")
        assert response.status_code == 200


def test_backend_reset():
    """Test resetting rate limit for a key."""
    backend = InMemoryRateLimitBackend()

    # Exhaust limit
    for i in range(5):
        backend.is_allowed("test_key", 5, 60)

    # Should be denied
    is_allowed, _, _ = backend.is_allowed("test_key", 5, 60)
    assert not is_allowed

    # Reset
    backend.reset("test_key")

    # Should be allowed again
    is_allowed, _, _ = backend.is_allowed("test_key", 5, 60)
    assert is_allowed


def test_backend_clear():
    """Test clearing all rate limits."""
    backend = InMemoryRateLimitBackend()

    # Add multiple keys
    backend.is_allowed("key1", 5, 60)
    backend.is_allowed("key2", 5, 60)

    # Clear all
    backend.clear()

    # Both should be allowed
    is_allowed, _, _ = backend.is_allowed("key1", 5, 60)
    assert is_allowed
    is_allowed, _, _ = backend.is_allowed("key2", 5, 60)
    assert is_allowed
