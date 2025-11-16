"""
Observability-focused FastAPI Application Example.

Demonstrates enterprise observability features:
- Structured logging
- OpenTelemetry tracing
- Prometheus metrics
"""

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.middleware.logging import (
    RequestIDMiddleware,
    StructuredLoggingMiddleware,
    CorrelationIDMiddleware,
    configure_structured_logging,
)
from fastapi.middleware.metrics import PrometheusMetrics, expose_metrics_endpoint

# Configure structured JSON logging
configure_structured_logging(
    log_level="INFO",
    json_format=True,
    include_timestamp=True,
)

app = FastAPI(title="Observable API", version="1.0.0")

# Add request ID tracking
app.add_middleware(RequestIDMiddleware)

# Add correlation ID tracking (for distributed systems)
app.add_middleware(CorrelationIDMiddleware)

# Add structured logging
app.add_middleware(StructuredLoggingMiddleware)

# Add Prometheus metrics
metrics = PrometheusMetrics(
    app,
    app_name="observable-api",
    prefix="myapp",
)

# Expose /metrics endpoint
expose_metrics_endpoint(app)


@app.get("/")
async def root(request: Request):
    """Root endpoint with request tracking."""
    return {
        "message": "Hello World",
        "request_id": request.state.request_id,
        "correlation_id": request.state.correlation_id,
    }


@app.get("/api/slow")
async def slow_endpoint():
    """
    Slow endpoint for testing.

    Metrics will show this endpoint has high latency.
    """
    import asyncio

    await asyncio.sleep(0.5)  # Simulate slow operation
    return {"message": "This was slow"}


@app.get("/api/error")
async def error_endpoint():
    """
    Error endpoint for testing.

    Metrics will track error rate.
    """
    raise Exception("Intentional error for testing")


# Custom business metrics
from fastapi.middleware.metrics import BusinessMetrics

business_metrics = BusinessMetrics()


@app.post("/api/orders")
async def create_order(amount: float):
    """
    Create order with business metrics tracking.
    """
    # Track business metrics
    business_metrics.orders_created.inc()
    business_metrics.order_value.observe(amount)

    return {
        "order_id": 123,
        "amount": amount,
        "status": "created",
    }


# Tracing example (requires OpenTelemetry setup)
from fastapi.middleware.opentelemetry import TracingHelper

tracing = TracingHelper()


@app.get("/api/traced")
async def traced_endpoint():
    """
    Endpoint with manual span creation.

    Demonstrates creating custom spans for specific operations.
    """
    with tracing.span("database_query") as span:
        span.set_attribute("query", "SELECT * FROM users")
        # Simulate database query
        import asyncio

        await asyncio.sleep(0.1)

    with tracing.span("cache_lookup") as span:
        span.set_attribute("key", "user:123")
        # Simulate cache lookup
        import asyncio

        await asyncio.sleep(0.05)

    return {"message": "Operation traced"}
