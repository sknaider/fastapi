"""
OpenTelemetry Integration for FastAPI.

Provides distributed tracing, metrics, and observability:
- Automatic span creation for HTTP requests
- Trace propagation across services
- Custom span attributes
- Integration with popular backends (Jaeger, Zipkin, DataDog, etc.)
"""

import time
from typing import Any, Callable, Dict, Optional

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    from opentelemetry import trace
    from opentelemetry.propagate import extract, inject
    from opentelemetry.trace import SpanKind, Status, StatusCode
    from opentelemetry.trace import Span as OTelSpan

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    trace = None
    SpanKind = None
    Status = None
    StatusCode = None


class OpenTelemetryMiddleware:
    """
    Middleware for OpenTelemetry distributed tracing.

    Automatically creates spans for HTTP requests and propagates trace context.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.opentelemetry import OpenTelemetryMiddleware
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter

        # Configure OpenTelemetry
        trace.set_tracer_provider(TracerProvider())
        jaeger_exporter = JaegerExporter(
            agent_host_name="localhost",
            agent_port=6831,
        )
        trace.get_tracer_provider().add_span_processor(
            BatchSpanProcessor(jaeger_exporter)
        )

        app = FastAPI()
        app.add_middleware(
            OpenTelemetryMiddleware,
            tracer_name="my-service",
        )
        ```

    Args:
        app: The ASGI application
        tracer_name: Name for the tracer
        exclude_paths: Paths to exclude from tracing
        get_custom_attributes: Function to add custom attributes to spans
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        tracer_name: str = "fastapi",
        exclude_paths: Optional[list] = None,
        get_custom_attributes: Optional[Callable[[Scope], Dict[str, Any]]] = None,
    ) -> None:
        if not OPENTELEMETRY_AVAILABLE:
            raise ImportError(
                "OpenTelemetry is not installed. "
                "Install it with: pip install opentelemetry-api opentelemetry-sdk"
            )

        self.app = app
        self.tracer = trace.get_tracer(tracer_name)
        self.exclude_paths = set(exclude_paths or ["/health", "/metrics"])
        self.get_custom_attributes = get_custom_attributes

    def _should_trace(self, path: str) -> bool:
        """Check if path should be traced."""
        return path not in self.exclude_paths

    def _get_span_name(self, scope: Scope) -> str:
        """Generate span name from scope."""
        method = scope.get("method", "")
        path = scope.get("path", "")
        return f"{method} {path}"

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP from scope."""
        headers = Headers(scope=scope)
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    def _set_span_attributes(self, span: "OTelSpan", scope: Scope) -> None:
        """Set standard attributes on span."""
        # HTTP attributes
        span.set_attribute("http.method", scope.get("method", ""))
        span.set_attribute("http.url", scope.get("path", ""))
        span.set_attribute("http.scheme", scope.get("scheme", ""))
        span.set_attribute("http.target", scope.get("path", ""))

        # Server attributes
        server = scope.get("server")
        if server:
            span.set_attribute("http.host", f"{server[0]}:{server[1]}")

        # Client attributes
        span.set_attribute("http.client_ip", self._get_client_ip(scope))

        # Query string
        query_string = scope.get("query_string", b"").decode()
        if query_string:
            span.set_attribute("http.query_string", query_string)

        # Request ID
        request_id = scope.get("state", {}).get("request_id")
        if request_id:
            span.set_attribute("http.request_id", request_id)

        # Custom attributes
        if self.get_custom_attributes:
            try:
                custom_attrs = self.get_custom_attributes(scope)
                for key, value in custom_attrs.items():
                    span.set_attribute(key, value)
            except Exception:
                pass  # Don't fail request if custom attributes fail

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not self._should_trace(path):
            await self.app(scope, receive, send)
            return

        # Extract trace context from headers
        headers = Headers(scope=scope)
        ctx = extract(dict(headers))

        # Create span
        span_name = self._get_span_name(scope)
        with self.tracer.start_as_current_span(
            span_name,
            context=ctx,
            kind=SpanKind.SERVER,
        ) as span:
            # Set standard attributes
            self._set_span_attributes(span, scope)

            # Track response
            status_code = 500
            start_time = time.time()

            async def send_with_tracing(message: Message) -> None:
                nonlocal status_code

                if message["type"] == "http.response.start":
                    status_code = message.get("status", 500)

                    # Set status code attribute
                    span.set_attribute("http.status_code", status_code)

                    # Set span status based on HTTP status
                    if status_code >= 500:
                        span.set_status(Status(StatusCode.ERROR))
                    elif status_code >= 400:
                        span.set_status(Status(StatusCode.ERROR))
                    else:
                        span.set_status(Status(StatusCode.OK))

                    # Inject trace context into response headers
                    headers_dict = dict(message.get("headers", []))
                    inject(headers_dict)
                    message["headers"] = list(headers_dict.items())

                elif message["type"] == "http.response.body":
                    # Record duration
                    duration_ms = (time.time() - start_time) * 1000
                    span.set_attribute("http.duration_ms", round(duration_ms, 2))

                await send(message)

            try:
                await self.app(scope, receive, send_with_tracing)
            except Exception as exc:
                # Record exception
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise


class TracingHelper:
    """
    Helper class for manual span creation in FastAPI endpoints.

    Example:
        ```python
        from fastapi import FastAPI, Request
        from fastapi.middleware.opentelemetry import TracingHelper

        app = FastAPI()
        tracing = TracingHelper()

        @app.get("/")
        async def root(request: Request):
            with tracing.span("database_query") as span:
                span.set_attribute("query", "SELECT * FROM users")
                # Perform database query
                return {"message": "Hello"}
        ```
    """

    def __init__(self, tracer_name: str = "fastapi"):
        if not OPENTELEMETRY_AVAILABLE:
            raise ImportError(
                "OpenTelemetry is not installed. "
                "Install it with: pip install opentelemetry-api opentelemetry-sdk"
            )
        self.tracer = trace.get_tracer(tracer_name)

    def span(self, name: str, **kwargs):
        """Create a new span."""
        return self.tracer.start_as_current_span(name, **kwargs)

    def get_current_span(self):
        """Get the current span."""
        return trace.get_current_span()

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Add an event to the current span."""
        span = trace.get_current_span()
        if span:
            span.add_event(name, attributes=attributes or {})

    def set_attribute(self, key: str, value: Any):
        """Set an attribute on the current span."""
        span = trace.get_current_span()
        if span:
            span.set_attribute(key, value)


def configure_opentelemetry(
    service_name: str,
    *,
    exporter_type: str = "console",
    jaeger_host: Optional[str] = None,
    jaeger_port: int = 6831,
    otlp_endpoint: Optional[str] = None,
) -> None:
    """
    Configure OpenTelemetry with common exporters.

    Args:
        service_name: Name of the service
        exporter_type: Type of exporter (console, jaeger, otlp)
        jaeger_host: Jaeger agent hostname
        jaeger_port: Jaeger agent port
        otlp_endpoint: OTLP endpoint URL

    Example:
        ```python
        from fastapi.middleware.opentelemetry import configure_opentelemetry

        configure_opentelemetry(
            service_name="my-api",
            exporter_type="jaeger",
            jaeger_host="localhost",
        )
        ```
    """
    if not OPENTELEMETRY_AVAILABLE:
        raise ImportError(
            "OpenTelemetry is not installed. "
            "Install it with: pip install opentelemetry-api opentelemetry-sdk"
        )

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Create resource
    resource = Resource(attributes={"service.name": service_name})

    # Create tracer provider
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    # Configure exporter
    if exporter_type == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        exporter = ConsoleSpanExporter()

    elif exporter_type == "jaeger":
        try:
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter

            exporter = JaegerExporter(
                agent_host_name=jaeger_host or "localhost",
                agent_port=jaeger_port,
            )
        except ImportError:
            raise ImportError(
                "Jaeger exporter not installed. "
                "Install it with: pip install opentelemetry-exporter-jaeger"
            )

    elif exporter_type == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint or "http://localhost:4317"
            )
        except ImportError:
            raise ImportError(
                "OTLP exporter not installed. "
                "Install it with: pip install opentelemetry-exporter-otlp"
            )

    else:
        raise ValueError(f"Unknown exporter type: {exporter_type}")

    # Add span processor
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
