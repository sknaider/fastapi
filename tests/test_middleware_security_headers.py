"""Tests for SecurityHeadersMiddleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi.middleware.security_headers import (
    SecurityHeadersMiddleware,
    StrictSecurityHeadersMiddleware,
)


def test_security_headers_middleware():
    """Test that security headers are added to responses."""
    app = FastAPI()

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "content-security-policy" in response.headers
    assert response.headers["content-security-policy"] == "default-src 'self'"
    assert "strict-transport-security" in response.headers
    assert "x-frame-options" in response.headers
    assert response.headers["x-frame-options"] == "DENY"
    assert "x-content-type-options" in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "referrer-policy" in response.headers


def test_custom_csp():
    """Test custom CSP policy."""
    app = FastAPI()

    app.add_middleware(
        SecurityHeadersMiddleware,
        csp="default-src 'self'; script-src 'self' https://cdn.example.com",
    )

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)
    response = client.get("/")

    assert "content-security-policy" in response.headers
    assert "https://cdn.example.com" in response.headers["content-security-policy"]


def test_disable_frame_options():
    """Test disabling X-Frame-Options."""
    app = FastAPI()

    app.add_middleware(SecurityHeadersMiddleware, frame_options=None)

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)
    response = client.get("/")

    assert "x-frame-options" not in response.headers


def test_hsts_configuration():
    """Test HSTS configuration."""
    app = FastAPI()

    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_max_age=63072000,
        hsts_include_subdomains=True,
        hsts_preload=True,
    )

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)
    response = client.get("/")

    hsts = response.headers["strict-transport-security"]
    assert "max-age=63072000" in hsts
    assert "includeSubDomains" in hsts
    assert "preload" in hsts


def test_strict_security_headers():
    """Test strict security headers middleware."""
    app = FastAPI()

    app.add_middleware(StrictSecurityHeadersMiddleware)

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_existing_headers_not_overwritten():
    """Test that existing headers are not overwritten."""
    app = FastAPI()

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/", response_headers={"X-Frame-Options": "SAMEORIGIN"})
    def root():
        from starlette.responses import Response
        return Response(
            content='{"message": "Hello"}',
            headers={"X-Frame-Options": "SAMEORIGIN"},
        )

    client = TestClient(app)
    response = client.get("/")

    # Middleware should not overwrite existing header
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
