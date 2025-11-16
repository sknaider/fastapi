"""
Error Tracking Integration for FastAPI.

Provides integration with error tracking services:
- Sentry integration
- Custom error handlers
- Error context enrichment
- Performance monitoring
"""

import sys
from typing import Any, Callable, Dict, Optional

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    sentry_sdk = None
    SentryAsgiMiddleware = None


class ErrorTrackingMiddleware:
    """
    Generic error tracking middleware.

    Captures exceptions and sends them to error tracking service.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.error_tracking import ErrorTrackingMiddleware

        app = FastAPI()
        app.add_middleware(
            ErrorTrackingMiddleware,
            on_error=lambda exc, scope: print(f"Error: {exc}"),
        )
        ```

    Args:
        app: The ASGI application
        on_error: Callback function called on errors
        capture_locals: Whether to capture local variables
        include_request_data: Whether to include request data in error context
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        on_error: Optional[Callable] = None,
        capture_locals: bool = True,
        include_request_data: bool = True,
    ) -> None:
        self.app = app
        self.on_error = on_error
        self.capture_locals = capture_locals
        self.include_request_data = include_request_data

    def _extract_request_context(self, scope: Scope) -> Dict[str, Any]:
        """Extract request context for error reporting."""
        context = {
            "method": scope.get("method"),
            "path": scope.get("path"),
            "query_string": scope.get("query_string", b"").decode(),
        }

        # Add headers
        if self.include_request_data:
            headers = Headers(scope=scope)
            context["headers"] = dict(headers)

            # Add client info
            client = scope.get("client")
            if client:
                context["client_ip"] = client[0]
                context["client_port"] = client[1]

            # Add user info if available
            user = scope.get("user")
            if user:
                if hasattr(user, "id"):
                    context["user_id"] = user.id
                if hasattr(user, "email"):
                    context["user_email"] = user.email

        return context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            # Extract context
            context = self._extract_request_context(scope)

            # Call error handler
            if self.on_error:
                try:
                    self.on_error(exc, scope, context)
                except Exception:
                    pass  # Don't fail on error handler failure

            # Re-raise exception
            raise


def configure_sentry(
    dsn: str,
    *,
    environment: Optional[str] = None,
    release: Optional[str] = None,
    traces_sample_rate: float = 0.1,
    profiles_sample_rate: float = 0.1,
    send_default_pii: bool = False,
    attach_stacktrace: bool = True,
    before_send: Optional[Callable] = None,
) -> None:
    """
    Configure Sentry error tracking.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.error_tracking import configure_sentry

        configure_sentry(
            dsn="https://your-sentry-dsn",
            environment="production",
            release="1.0.0",
            traces_sample_rate=0.2,
        )

        app = FastAPI()
        ```

    Args:
        dsn: Sentry DSN
        environment: Environment name (e.g., production, staging)
        release: Release version
        traces_sample_rate: Percentage of transactions to trace (0.0 to 1.0)
        profiles_sample_rate: Percentage of transactions to profile (0.0 to 1.0)
        send_default_pii: Whether to send personally identifiable information
        attach_stacktrace: Whether to attach stack traces
        before_send: Callback to modify events before sending
    """
    if not SENTRY_AVAILABLE:
        raise ImportError(
            "Sentry SDK is not installed. "
            "Install it with: pip install sentry-sdk"
        )

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        send_default_pii=send_default_pii,
        attach_stacktrace=attach_stacktrace,
        before_send=before_send,
        integrations=[],  # We'll add ASGI integration via middleware
    )


class SentryMiddleware:
    """
    Sentry integration middleware for FastAPI.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.error_tracking import (
            configure_sentry,
            SentryMiddleware,
        )

        configure_sentry(dsn="https://your-sentry-dsn")

        app = FastAPI()
        app.add_middleware(SentryMiddleware)
        ```

    Args:
        app: The ASGI application
        capture_all_errors: Whether to capture all errors (including handled ones)
        set_user: Function to extract user from scope
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        capture_all_errors: bool = False,
        set_user: Optional[Callable[[Scope], Dict[str, Any]]] = None,
    ) -> None:
        if not SENTRY_AVAILABLE:
            raise ImportError(
                "Sentry SDK is not installed. "
                "Install it with: pip install sentry-sdk"
            )

        self.app = SentryAsgiMiddleware(app)
        self.capture_all_errors = capture_all_errors
        self.set_user = set_user

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Set user context if available
        if self.set_user:
            try:
                user_data = self.set_user(scope)
                sentry_sdk.set_user(user_data)
            except Exception:
                pass

        # Set request context
        with sentry_sdk.configure_scope() as sentry_scope:
            sentry_scope.set_context(
                "request",
                {
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "query_string": scope.get("query_string", b"").decode(),
                },
            )

            # Add request ID if available
            request_id = scope.get("state", {}).get("request_id")
            if request_id:
                sentry_scope.set_tag("request_id", request_id)

        await self.app(scope, receive, send)


class ErrorContextMiddleware:
    """
    Middleware to enrich error context with additional data.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.error_tracking import ErrorContextMiddleware

        app = FastAPI()
        app.add_middleware(
            ErrorContextMiddleware,
            extra_context={"app_version": "1.0.0"},
        )
        ```

    Args:
        app: The ASGI application
        extra_context: Additional context to add to all errors
        context_extractor: Function to extract context from scope
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        extra_context: Optional[Dict[str, Any]] = None,
        context_extractor: Optional[Callable[[Scope], Dict[str, Any]]] = None,
    ) -> None:
        self.app = app
        self.extra_context = extra_context or {}
        self.context_extractor = context_extractor

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Add context to scope
        if "error_context" not in scope:
            scope["error_context"] = {}

        scope["error_context"].update(self.extra_context)

        # Extract additional context
        if self.context_extractor:
            try:
                custom_context = self.context_extractor(scope)
                scope["error_context"].update(custom_context)
            except Exception:
                pass

        await self.app(scope, receive, send)


def capture_exception(
    exception: Exception,
    *,
    level: str = "error",
    tags: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Manually capture an exception to Sentry.

    Example:
        ```python
        from fastapi.middleware.error_tracking import capture_exception

        try:
            # Some code that might fail
            risky_operation()
        except Exception as e:
            capture_exception(
                e,
                level="warning",
                tags={"component": "payment"},
                extra={"order_id": 123},
            )
        ```

    Args:
        exception: Exception to capture
        level: Severity level (debug, info, warning, error, fatal)
        tags: Custom tags
        extra: Extra context data

    Returns:
        Event ID if captured, None otherwise
    """
    if not SENTRY_AVAILABLE:
        return None

    with sentry_sdk.configure_scope() as scope:
        if tags:
            for key, value in tags.items():
                scope.set_tag(key, value)

        if extra:
            for key, value in extra.items():
                scope.set_extra(key, value)

        scope.level = level

    return sentry_sdk.capture_exception(exception)


def capture_message(
    message: str,
    *,
    level: str = "info",
    tags: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Manually capture a message to Sentry.

    Example:
        ```python
        from fastapi.middleware.error_tracking import capture_message

        capture_message(
            "User performed important action",
            level="info",
            tags={"user_id": 123},
            extra={"action": "purchase"},
        )
        ```

    Args:
        message: Message to capture
        level: Severity level
        tags: Custom tags
        extra: Extra context data

    Returns:
        Event ID if captured, None otherwise
    """
    if not SENTRY_AVAILABLE:
        return None

    with sentry_sdk.configure_scope() as scope:
        if tags:
            for key, value in tags.items():
                scope.set_tag(key, value)

        if extra:
            for key, value in extra.items():
                scope.set_extra(key, value)

        scope.level = level

    return sentry_sdk.capture_message(message)
