"""Tests for logging middleware."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from fastapi.middleware.logging import (
    CorrelationIDMiddleware,
    RequestIDMiddleware,
    StructuredLoggingMiddleware,
)


def test_request_id_middleware():
    """Test that request ID is added to requests."""
    app = FastAPI()

    app.add_middleware(RequestIDMiddleware)

    @app.get("/")
    def root(request: Request):
        return {"request_id": request.state.request_id}

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "request_id" in response.json()
    assert "x-request-id" in response.headers


def test_request_id_from_header():
    """Test using request ID from client header."""
    app = FastAPI()

    app.add_middleware(RequestIDMiddleware)

    @app.get("/")
    def root(request: Request):
        return {"request_id": request.state.request_id}

    client = TestClient(app)
    response = client.get("/", headers={"X-Request-ID": "custom-id-123"})

    assert response.status_code == 200
    assert response.json()["request_id"] == "custom-id-123"
    assert response.headers["x-request-id"] == "custom-id-123"


def test_correlation_id_middleware():
    """Test correlation ID middleware."""
    app = FastAPI()

    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/")
    def root(request: Request):
        return {"correlation_id": request.state.correlation_id}

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "correlation_id" in response.json()
    assert "x-correlation-id" in response.headers


def test_structured_logging_middleware(caplog):
    """Test structured logging middleware."""
    app = FastAPI()

    app.add_middleware(StructuredLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    @app.get("/")
    def root():
        return {"message": "Hello"}

    client = TestClient(app)

    with caplog.at_level("INFO"):
        response = client.get("/")

    assert response.status_code == 200
    # Check that log was created
    assert len(caplog.records) > 0


def test_skip_paths():
    """Test skipping paths from logging."""
    app = FastAPI()

    app.add_middleware(
        StructuredLoggingMiddleware,
        skip_paths=["/health"],
    )

    @app.get("/")
    def root():
        return {"message": "Hello"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(app)

    # / should be logged, /health should not
    client.get("/")
    client.get("/health")
