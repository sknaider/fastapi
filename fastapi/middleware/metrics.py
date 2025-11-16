"""
Metrics Collection Middleware for FastAPI.

Provides enterprise-grade metrics collection:
- Prometheus metrics export
- Request/response metrics
- Custom business metrics
- Performance monitoring
"""

import time
from typing import Callable, Optional

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    from prometheus_client import (
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = None
    Gauge = None
    Histogram = None


class PrometheusMetrics:
    """
    Prometheus metrics collector for FastAPI.

    Provides standard HTTP metrics:
    - Request count by method, path, and status
    - Request duration histogram
    - Requests in progress gauge
    - Response size histogram

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.metrics import PrometheusMetrics

        app = FastAPI()
        metrics = PrometheusMetrics(app)

        # Metrics endpoint
        @app.get("/metrics")
        async def metrics_endpoint():
            return Response(
                metrics.generate_metrics(),
                media_type="text/plain",
            )
        ```
    """

    def __init__(
        self,
        app: Optional[ASGIApp] = None,
        *,
        app_name: str = "fastapi",
        prefix: str = "fastapi",
        exclude_paths: Optional[list] = None,
        buckets: Optional[list] = None,
    ) -> None:
        if not PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus_client is not installed. "
                "Install it with: pip install prometheus-client"
            )

        self.app_name = app_name
        self.prefix = prefix
        self.exclude_paths = set(exclude_paths or ["/metrics", "/health"])
        self.buckets = buckets or [
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
            5.0,
            10.0,
        ]

        # Initialize metrics
        self.request_count = Counter(
            f"{prefix}_requests_total",
            "Total request count",
            ["method", "path", "status_code"],
        )

        self.request_duration = Histogram(
            f"{prefix}_request_duration_seconds",
            "Request duration in seconds",
            ["method", "path"],
            buckets=self.buckets,
        )

        self.requests_in_progress = Gauge(
            f"{prefix}_requests_in_progress",
            "Requests in progress",
            ["method", "path"],
        )

        self.response_size = Histogram(
            f"{prefix}_response_size_bytes",
            "Response size in bytes",
            ["method", "path"],
        )

        self.exceptions_count = Counter(
            f"{prefix}_exceptions_total",
            "Total exception count",
            ["method", "path", "exception_type"],
        )

        if app:
            app.add_middleware(PrometheusMiddleware, metrics=self)

    def generate_metrics(self) -> bytes:
        """Generate Prometheus metrics output."""
        return generate_latest(REGISTRY)


class PrometheusMiddleware:
    """
    Middleware for Prometheus metrics collection.

    Args:
        app: The ASGI application
        metrics: PrometheusMetrics instance
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: Optional[PrometheusMetrics] = None,
    ) -> None:
        self.app = app
        self.metrics = metrics or PrometheusMetrics()

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from metrics."""
        return path in self.metrics.exclude_paths

    def _get_path_template(self, scope: Scope) -> str:
        """Extract path template from scope."""
        # Try to get matched route
        for route in scope.get("route", {}).get("path", ""):
            return route

        # Fallback to actual path
        return scope.get("path", "unknown")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if self._should_exclude(path):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path_template = self._get_path_template(scope)

        # Track request in progress
        self.metrics.requests_in_progress.labels(
            method=method, path=path_template
        ).inc()

        start_time = time.time()
        status_code = 500
        response_size = 0

        async def send_with_metrics(message: Message) -> None:
            nonlocal status_code, response_size

            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)

            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response_size = len(body)

                # Record metrics
                duration = time.time() - start_time

                self.metrics.request_count.labels(
                    method=method, path=path_template, status_code=status_code
                ).inc()

                self.metrics.request_duration.labels(
                    method=method, path=path_template
                ).observe(duration)

                self.metrics.response_size.labels(
                    method=method, path=path_template
                ).observe(response_size)

                self.metrics.requests_in_progress.labels(
                    method=method, path=path_template
                ).dec()

            await send(message)

        try:
            await self.app(scope, receive, send_with_metrics)
        except Exception as exc:
            # Record exception
            self.metrics.exceptions_count.labels(
                method=method,
                path=path_template,
                exception_type=type(exc).__name__,
            ).inc()

            # Decrement in-progress counter
            self.metrics.requests_in_progress.labels(
                method=method, path=path_template
            ).dec()

            raise


class BusinessMetrics:
    """
    Helper class for custom business metrics.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.metrics import BusinessMetrics

        app = FastAPI()
        business_metrics = BusinessMetrics()

        @app.post("/orders")
        async def create_order():
            business_metrics.orders_created.inc()
            business_metrics.order_value.observe(99.99)
            return {"order_id": 123}
        ```
    """

    def __init__(self, prefix: str = "business") -> None:
        if not PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus_client is not installed. "
                "Install it with: pip install prometheus-client"
            )

        self.prefix = prefix

        # Example business metrics
        self.orders_created = Counter(
            f"{prefix}_orders_created_total",
            "Total orders created",
        )

        self.order_value = Histogram(
            f"{prefix}_order_value",
            "Order value distribution",
            buckets=[10, 50, 100, 500, 1000, 5000],
        )

        self.active_users = Gauge(
            f"{prefix}_active_users",
            "Number of active users",
        )

        self.api_calls = Counter(
            f"{prefix}_api_calls_total",
            "Total external API calls",
            ["service"],
        )

    def create_counter(self, name: str, description: str, labels: Optional[list] = None):
        """Create a custom counter metric."""
        return Counter(f"{self.prefix}_{name}", description, labels or [])

    def create_gauge(self, name: str, description: str, labels: Optional[list] = None):
        """Create a custom gauge metric."""
        return Gauge(f"{self.prefix}_{name}", description, labels or [])

    def create_histogram(
        self,
        name: str,
        description: str,
        labels: Optional[list] = None,
        buckets: Optional[list] = None,
    ):
        """Create a custom histogram metric."""
        return Histogram(
            f"{self.prefix}_{name}",
            description,
            labels or [],
            buckets=buckets,
        )


def expose_metrics_endpoint(app, path: str = "/metrics"):
    """
    Convenience function to add metrics endpoint to FastAPI app.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.metrics import (
            PrometheusMetrics,
            expose_metrics_endpoint,
        )

        app = FastAPI()
        metrics = PrometheusMetrics(app)
        expose_metrics_endpoint(app)
        ```

    Args:
        app: FastAPI application
        path: Metrics endpoint path
    """
    if not PROMETHEUS_AVAILABLE:
        raise ImportError(
            "prometheus_client is not installed. "
            "Install it with: pip install prometheus-client"
        )

    @app.get(path)
    async def metrics():
        from prometheus_client import generate_latest

        return Response(generate_latest(REGISTRY), media_type="text/plain")
