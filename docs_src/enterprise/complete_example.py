"""
Complete Enterprise FastAPI Application Example.

This example demonstrates all enterprise features:
- Security headers
- Rate limiting
- Structured logging
- Audit logging
- OpenTelemetry tracing
- Circuit breaker
- Caching
- Metrics
- Error tracking
"""

import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response

# Enterprise middleware
from fastapi.middleware.security_headers import SecurityHeadersMiddleware
from fastapi.middleware.rate_limit import RateLimitMiddleware
from fastapi.middleware.logging import (
    RequestIDMiddleware,
    StructuredLoggingMiddleware,
    configure_structured_logging,
)
from fastapi.middleware.audit import AuditLoggingMiddleware, AuditEventType, get_audit_logger
from fastapi.middleware.cache import CacheMiddleware
from fastapi.middleware.circuit_breaker import CircuitBreakerMiddleware
from fastapi.middleware.metrics import PrometheusMetrics, expose_metrics_endpoint

# Configure structured logging
configure_structured_logging(
    log_level="INFO",
    json_format=True,
)

# Create FastAPI app
app = FastAPI(
    title="Enterprise API",
    version="1.0.0",
    description="Production-ready API with enterprise features",
)

# Add middleware stack (order matters!)
# 1. Metrics (outermost)
metrics = PrometheusMetrics(app, app_name="enterprise-api")

# 2. Security headers
app.add_middleware(
    SecurityHeadersMiddleware,
    csp="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
    hsts_max_age=31536000,
)

# 3. Rate limiting
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=60,
    requests_per_hour=1000,
)

# 4. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Request ID
app.add_middleware(RequestIDMiddleware)

# 6. Structured logging
app.add_middleware(StructuredLoggingMiddleware)

# 7. Audit logging
app.add_middleware(
    AuditLoggingMiddleware,
    audit_paths=["/api/admin"],
)

# 8. Caching
app.add_middleware(
    CacheMiddleware,
    default_ttl=60,
    cache_paths=["/api/data"],
)

# 9. Circuit breaker
app.add_middleware(
    CircuitBreakerMiddleware,
    failure_threshold=5,
    timeout=60,
    protected_paths=["/api/external"],
)

# 10. GZIP (innermost)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Health check endpoint
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# Metrics endpoint
expose_metrics_endpoint(app, path="/metrics")


# Example protected endpoint
@app.get("/api/data")
async def get_data():
    """
    Cached endpoint example.

    This endpoint is cached for 60 seconds.
    """
    return {
        "data": [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"},
        ]
    }


# Example admin endpoint with audit logging
@app.post("/api/admin/users")
async def create_user(request: Request):
    """
    Admin endpoint with audit logging.

    All requests to /api/admin/* are audited.
    """
    audit_logger = get_audit_logger()

    # Log audit event
    audit_logger.log(
        event_type=AuditEventType.USER_CREATED,
        actor="admin@example.com",
        resource="users",
        action="CREATE",
        details={"user_id": 123},
    )

    return {"user_id": 123, "message": "User created"}


# Example endpoint that might fail (circuit breaker)
@app.get("/api/external")
async def call_external_service():
    """
    External service call protected by circuit breaker.

    If this endpoint fails repeatedly, circuit will open.
    """
    # Simulate external API call
    import random

    if random.random() < 0.3:  # 30% failure rate
        raise HTTPException(status_code=503, detail="External service unavailable")

    return {"data": "External service response"}


# Example endpoint to demonstrate request ID
@app.get("/api/request-id")
async def get_request_id(request: Request):
    """Get the current request ID."""
    return {
        "request_id": request.state.request_id,
        "message": "Each request has a unique ID",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
