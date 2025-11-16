"""
Structured Logging Middleware for FastAPI.

Provides enterprise-grade logging with:
- Request ID tracking
- Structured JSON logging
- Request/response logging
- Performance metrics
- Correlation IDs for distributed tracing
"""

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestIDMiddleware:
    """
    Middleware to add unique request ID to each request.

    The request ID can be:
    1. Provided by client via X-Request-ID header
    2. Auto-generated UUID if not provided

    Example:
        ```python
        from fastapi import FastAPI, Request
        from fastapi.middleware.logging import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/")
        async def root(request: Request):
            request_id = request.state.request_id
            return {"request_id": request_id}
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = "X-Request-ID",
        generator: Optional[Callable[[], str]] = None,
    ) -> None:
        self.app = app
        self.header_name = header_name
        self.generator = generator or self._default_generator

    def _default_generator(self) -> str:
        """Generate a UUID4 request ID."""
        return str(uuid.uuid4())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Get request ID from header or generate new one
        headers = Headers(scope=scope)
        request_id = headers.get(self.header_name.lower()) or self.generator()

        # Store in scope state
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[self.header_name.encode().lower()] = request_id.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class StructuredLoggingMiddleware:
    """
    Middleware for structured logging with request/response details.

    Logs all HTTP requests with:
    - Request ID
    - Method and path
    - Status code
    - Response time
    - Client IP
    - User agent
    - Request/response size

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.logging import (
            RequestIDMiddleware,
            StructuredLoggingMiddleware,
        )

        app = FastAPI()
        app.add_middleware(StructuredLoggingMiddleware)
        app.add_middleware(RequestIDMiddleware)
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        logger: Optional[logging.Logger] = None,
        log_request_body: bool = False,
        log_response_body: bool = False,
        skip_paths: Optional[list] = None,
        log_level: int = logging.INFO,
    ) -> None:
        self.app = app
        self.logger = logger or logging.getLogger("fastapi.request")
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.skip_paths = set(skip_paths or ["/health", "/metrics"])
        self.log_level = log_level

    def _should_skip(self, path: str) -> bool:
        """Check if path should be skipped from logging."""
        return path in self.skip_paths

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP from scope."""
        headers = Headers(scope=scope)
        # Check X-Forwarded-For first (proxy/load balancer)
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if self._should_skip(path):
            await self.app(scope, receive, send)
            return

        # Extract request information
        method = scope.get("method", "")
        headers = Headers(scope=scope)
        user_agent = headers.get("user-agent", "")
        request_id = scope.get("state", {}).get("request_id", "")
        client_ip = self._get_client_ip(scope)

        # Track request timing
        start_time = time.time()

        # Response tracking
        status_code = 500
        response_headers = {}

        async def send_with_logging(message: Message) -> None:
            nonlocal status_code, response_headers

            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                response_headers = dict(message.get("headers", []))

            elif message["type"] == "http.response.body":
                # Log after response is complete
                duration_ms = (time.time() - start_time) * 1000

                log_data = {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                }

                # Add query string if present
                query_string = scope.get("query_string", b"").decode()
                if query_string:
                    log_data["query_string"] = query_string

                # Log structured data
                self.logger.log(
                    self.log_level,
                    json.dumps(log_data),
                    extra=log_data,
                )

            await send(message)

        await self.app(scope, receive, send_with_logging)


class CorrelationIDMiddleware:
    """
    Middleware for correlation ID tracking across distributed systems.

    Supports both X-Correlation-ID and X-Request-ID headers.
    Useful for tracing requests across microservices.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.logging import CorrelationIDMiddleware

        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = "X-Correlation-ID",
        generator: Optional[Callable[[], str]] = None,
    ) -> None:
        self.app = app
        self.header_name = header_name
        self.generator = generator or self._default_generator

    def _default_generator(self) -> str:
        """Generate a UUID4 correlation ID."""
        return str(uuid.uuid4())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Get correlation ID from header or generate new one
        headers = Headers(scope=scope)
        correlation_id = (
            headers.get(self.header_name.lower())
            or headers.get("x-request-id")
            or self.generator()
        )

        # Store in scope state
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["correlation_id"] = correlation_id

        async def send_with_correlation_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[self.header_name.encode().lower()] = correlation_id.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_with_correlation_id)


def configure_structured_logging(
    *,
    log_level: str = "INFO",
    json_format: bool = True,
    include_timestamp: bool = True,
) -> None:
    """
    Configure structured logging for FastAPI application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON format for logs
        include_timestamp: Include timestamp in logs

    Example:
        ```python
        from fastapi.middleware.logging import configure_structured_logging

        configure_structured_logging(log_level="INFO", json_format=True)
        ```
    """
    if json_format:
        # JSON formatter
        class JSONFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                log_data = {
                    "timestamp": self.formatTime(record, self.datefmt)
                    if include_timestamp
                    else None,
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }

                # Add extra fields
                if hasattr(record, "request_id"):
                    log_data["request_id"] = record.request_id
                if hasattr(record, "correlation_id"):
                    log_data["correlation_id"] = record.correlation_id

                # Remove None values
                log_data = {k: v for k, v in log_data.items() if v is not None}

                return json.dumps(log_data)

        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
    else:
        # Standard formatter
        format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(format_str))

    # Configure root logger
    logging.root.setLevel(log_level)
    logging.root.addHandler(handler)

    # Configure FastAPI logger
    fastapi_logger = logging.getLogger("fastapi")
    fastapi_logger.setLevel(log_level)
    fastapi_logger.addHandler(handler)
