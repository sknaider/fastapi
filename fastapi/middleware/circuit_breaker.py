"""
Circuit Breaker Pattern Middleware for FastAPI.

Implements the circuit breaker pattern for resilient external service calls:
- Prevents cascading failures
- Automatic failure detection
- Configurable thresholds and timeouts
- Half-open state for recovery testing
"""

import time
from enum import Enum
from typing import Callable, Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker implementation.

    Example:
        ```python
        from fastapi.middleware.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker(
            failure_threshold=5,
            timeout=60,
            expected_exception=HTTPException,
        )

        @breaker
        async def call_external_api():
            # Call external service
            pass
        ```

    Args:
        failure_threshold: Number of failures before opening circuit
        timeout: Seconds before attempting to close circuit
        expected_exception: Exception type that triggers circuit
        recovery_timeout: Seconds to wait in half-open state
        half_open_max_calls: Max calls to allow in half-open state
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exception: type = Exception,
        recovery_timeout: int = 30,
        half_open_max_calls: int = 3,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        # State
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.opened_at: Optional[float] = None
        self.half_open_calls = 0

    def call(self, func: Callable, *args, **kwargs):
        """
        Call function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function return value

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Original exception if circuit is closed
        """
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to_half_open()
            else:
                raise CircuitBreakerError(
                    f"Circuit breaker is OPEN. Try again in {self._time_until_reset():.0f}s"
                )

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerError(
                    "Circuit breaker is HALF_OPEN with max calls reached"
                )

        try:
            self.half_open_calls += 1 if self.state == CircuitState.HALF_OPEN else 0
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    async def async_call(self, func: Callable, *args, **kwargs):
        """Async version of call()."""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to_half_open()
            else:
                raise CircuitBreakerError(
                    f"Circuit breaker is OPEN. Try again in {self._time_until_reset():.0f}s"
                )

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerError(
                    "Circuit breaker is HALF_OPEN with max calls reached"
                )

        try:
            self.half_open_calls += 1 if self.state == CircuitState.HALF_OPEN else 0
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        self.failure_count = 0
        self.success_count += 1

        if self.state == CircuitState.HALF_OPEN:
            if self.success_count >= self.half_open_max_calls:
                self._transition_to_closed()

    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self._transition_to_open()
        elif self.failure_count >= self.failure_threshold:
            self._transition_to_open()

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.opened_at is None:
            return False
        return (time.time() - self.opened_at) >= self.timeout

    def _time_until_reset(self) -> float:
        """Calculate time until circuit can be reset."""
        if self.opened_at is None:
            return 0
        elapsed = time.time() - self.opened_at
        return max(0, self.timeout - elapsed)

    def _transition_to_open(self) -> None:
        """Transition to OPEN state."""
        self.state = CircuitState.OPEN
        self.opened_at = time.time()
        self.half_open_calls = 0

    def _transition_to_half_open(self) -> None:
        """Transition to HALF_OPEN state."""
        self.state = CircuitState.HALF_OPEN
        self.half_open_calls = 0
        self.success_count = 0

    def _transition_to_closed(self) -> None:
        """Transition to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.opened_at = None
        self.half_open_calls = 0

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._transition_to_closed()

    def get_state(self) -> dict:
        """Get current circuit breaker state."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "opened_at": self.opened_at,
            "time_until_reset": self._time_until_reset() if self.opened_at else 0,
        }

    def __call__(self, func: Callable) -> Callable:
        """Decorator interface."""

        async def async_wrapper(*args, **kwargs):
            return await self.async_call(func, *args, **kwargs)

        def sync_wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""

    pass


class CircuitBreakerMiddleware:
    """
    Middleware for circuit breaker pattern at HTTP endpoint level.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.circuit_breaker import CircuitBreakerMiddleware

        app = FastAPI()
        app.add_middleware(
            CircuitBreakerMiddleware,
            failure_threshold=5,
            timeout=60,
            protected_paths=["/api/external"],
        )
        ```

    Args:
        app: The ASGI application
        failure_threshold: Number of failures before opening circuit
        timeout: Seconds before attempting to close circuit
        protected_paths: List of paths to protect with circuit breaker
        status_codes_to_track: HTTP status codes that count as failures
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        failure_threshold: int = 5,
        timeout: int = 60,
        protected_paths: Optional[list] = None,
        status_codes_to_track: Optional[list] = None,
    ) -> None:
        self.app = app
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.protected_paths = protected_paths or []
        self.status_codes_to_track = status_codes_to_track or [500, 502, 503, 504]

        # Circuit breakers per path
        self.breakers = {}

    def _get_breaker(self, path: str) -> CircuitBreaker:
        """Get or create circuit breaker for path."""
        if path not in self.breakers:
            self.breakers[path] = CircuitBreaker(
                failure_threshold=self.failure_threshold,
                timeout=self.timeout,
            )
        return self.breakers[path]

    def _should_protect(self, path: str) -> bool:
        """Check if path should be protected by circuit breaker."""
        if not self.protected_paths:
            return False
        return any(path.startswith(prefix) for prefix in self.protected_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not self._should_protect(path):
            await self.app(scope, receive, send)
            return

        breaker = self._get_breaker(path)

        # Check circuit state before processing request
        if breaker.state == CircuitState.OPEN:
            if breaker._should_attempt_reset():
                breaker._transition_to_half_open()
            else:
                # Circuit is open, return error
                response = JSONResponse(
                    {
                        "error": "Service Unavailable",
                        "message": "Circuit breaker is OPEN due to repeated failures",
                        "retry_after": int(breaker._time_until_reset()),
                        "circuit_state": breaker.get_state(),
                    },
                    status_code=503,
                    headers={
                        "Retry-After": str(int(breaker._time_until_reset())),
                    },
                )
                await response(scope, receive, send)
                return

        # Track response status
        status_code = 200

        async def send_with_circuit_breaker(message):
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)

            elif message["type"] == "http.response.body":
                # Update circuit breaker based on status code
                if status_code in self.status_codes_to_track:
                    breaker._on_failure()
                else:
                    breaker._on_success()

            await send(message)

        try:
            await self.app(scope, receive, send_with_circuit_breaker)
        except Exception as e:
            breaker._on_failure()
            raise
