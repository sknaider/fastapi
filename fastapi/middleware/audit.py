"""
Audit Logging System for FastAPI.

Enterprise-grade audit logging for compliance and security:
- User action tracking
- Data access logging
- Administrative operations
- Security events
- Compliance auditing (SOC2, HIPAA, PCI-DSS)
"""

import json
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AuditEventType(str, Enum):
    """Types of audit events."""

    # Authentication & Authorization
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    TOKEN_CREATED = "auth.token.created"
    TOKEN_REVOKED = "auth.token.revoked"
    PERMISSION_GRANTED = "auth.permission.granted"
    PERMISSION_DENIED = "auth.permission.denied"

    # Data Access
    DATA_READ = "data.read"
    DATA_CREATED = "data.created"
    DATA_UPDATED = "data.updated"
    DATA_DELETED = "data.deleted"
    DATA_EXPORTED = "data.exported"

    # Administrative
    ADMIN_ACTION = "admin.action"
    CONFIG_CHANGED = "admin.config.changed"
    USER_CREATED = "admin.user.created"
    USER_UPDATED = "admin.user.updated"
    USER_DELETED = "admin.user.deleted"
    ROLE_CHANGED = "admin.role.changed"

    # Security
    SECURITY_ALERT = "security.alert"
    SUSPICIOUS_ACTIVITY = "security.suspicious"
    RATE_LIMIT_EXCEEDED = "security.rate_limit"
    UNAUTHORIZED_ACCESS = "security.unauthorized"

    # System
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"
    API_CALL = "system.api_call"


class AuditEvent:
    """Audit event data structure."""

    def __init__(
        self,
        event_type: AuditEventType,
        actor: str,
        resource: Optional[str] = None,
        action: Optional[str] = None,
        result: str = "success",
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.event_type = event_type
        self.actor = actor
        self.resource = resource
        self.action = action
        self.result = result
        self.details = details or {}
        self.request_id = request_id
        self.correlation_id = correlation_id
        self.client_ip = client_ip
        self.user_agent = user_agent
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert audit event to dictionary."""
        data = {
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "actor": self.actor,
            "result": self.result,
        }

        if self.resource:
            data["resource"] = self.resource
        if self.action:
            data["action"] = self.action
        if self.request_id:
            data["request_id"] = self.request_id
        if self.correlation_id:
            data["correlation_id"] = self.correlation_id
        if self.client_ip:
            data["client_ip"] = self.client_ip
        if self.user_agent:
            data["user_agent"] = self.user_agent
        if self.details:
            data["details"] = self.details

        return data

    def to_json(self) -> str:
        """Convert audit event to JSON string."""
        return json.dumps(self.to_dict())


class AuditLogger:
    """
    Audit logger for enterprise compliance.

    Example:
        ```python
        from fastapi.middleware.audit import AuditLogger, AuditEventType

        audit_logger = AuditLogger()

        audit_logger.log_event(
            event_type=AuditEventType.DATA_CREATED,
            actor="user@example.com",
            resource="users/123",
            action="CREATE",
            details={"user_id": 123}
        )
        ```
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        *,
        async_handler: Optional[Callable] = None,
    ) -> None:
        self.logger = logger or logging.getLogger("fastapi.audit")
        self.async_handler = async_handler

        # Ensure logger is configured
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - AUDIT - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def log_event(self, event: AuditEvent) -> None:
        """Log an audit event."""
        self.logger.info(event.to_json(), extra=event.to_dict())

        # Call async handler if provided (e.g., send to external system)
        if self.async_handler:
            try:
                self.async_handler(event)
            except Exception as e:
                self.logger.error(f"Audit async handler failed: {e}")

    def log(
        self,
        event_type: AuditEventType,
        actor: str,
        **kwargs,
    ) -> None:
        """Convenience method to log an audit event."""
        event = AuditEvent(event_type=event_type, actor=actor, **kwargs)
        self.log_event(event)


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """Set the global audit logger instance."""
    global _audit_logger
    _audit_logger = logger


class AuditLoggingMiddleware:
    """
    Middleware for automatic audit logging of HTTP requests.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.audit import AuditLoggingMiddleware

        app = FastAPI()
        app.add_middleware(
            AuditLoggingMiddleware,
            audit_paths=["/api/admin", "/api/users"],
        )
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        audit_logger: Optional[AuditLogger] = None,
        audit_paths: Optional[list] = None,
        exclude_paths: Optional[list] = None,
        get_actor: Optional[Callable[[Scope], str]] = None,
    ) -> None:
        self.app = app
        self.audit_logger = audit_logger or get_audit_logger()
        self.audit_paths = audit_paths  # If None, audit all paths
        self.exclude_paths = set(exclude_paths or ["/health", "/metrics", "/docs"])
        self.get_actor = get_actor or self._default_get_actor

    def _default_get_actor(self, scope: Scope) -> str:
        """Default actor extraction (from user or IP)."""
        # Try to get authenticated user
        user = scope.get("user")
        if user:
            if hasattr(user, "email"):
                return user.email
            elif hasattr(user, "username"):
                return user.username
            elif hasattr(user, "id"):
                return f"user:{user.id}"

        # Fallback to IP address
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        return "unknown"

    def _should_audit(self, path: str, method: str) -> bool:
        """Check if request should be audited."""
        # Skip excluded paths
        if path in self.exclude_paths:
            return False

        # If audit_paths is specified, only audit those paths
        if self.audit_paths:
            return any(path.startswith(prefix) for prefix in self.audit_paths)

        # Audit all mutating operations by default
        return method in ["POST", "PUT", "PATCH", "DELETE"]

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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        if not self._should_audit(path, method):
            await self.app(scope, receive, send)
            return

        # Extract request information
        headers = Headers(scope=scope)
        user_agent = headers.get("user-agent", "")
        request_id = scope.get("state", {}).get("request_id", "")
        correlation_id = scope.get("state", {}).get("correlation_id", "")
        actor = self.get_actor(scope)
        client_ip = self._get_client_ip(scope)

        # Track response
        status_code = 500

        async def send_with_audit(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)

            elif message["type"] == "http.response.body":
                # Log audit event
                result = "success" if status_code < 400 else "failure"

                event = AuditEvent(
                    event_type=AuditEventType.API_CALL,
                    actor=actor,
                    resource=path,
                    action=method,
                    result=result,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    details={
                        "status_code": status_code,
                        "query_string": scope.get("query_string", b"").decode(),
                    },
                )

                self.audit_logger.log_event(event)

            await send(message)

        await self.app(scope, receive, send_with_audit)
