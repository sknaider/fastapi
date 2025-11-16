"""Tests for CircuitBreaker."""

import pytest

from fastapi.middleware.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
)


def test_circuit_breaker_closed():
    """Test circuit breaker in closed state."""
    breaker = CircuitBreaker(failure_threshold=3)

    # Circuit should be closed
    assert breaker.state == CircuitState.CLOSED

    # Successful calls should work
    result = breaker.call(lambda: "success")
    assert result == "success"
    assert breaker.state == CircuitState.CLOSED


def test_circuit_breaker_opens_on_failures():
    """Test circuit breaker opens after failures."""
    breaker = CircuitBreaker(failure_threshold=3)

    # Simulate failures
    for i in range(3):
        try:
            breaker.call(lambda: 1 / 0)  # Will raise ZeroDivisionError
        except ZeroDivisionError:
            pass

    # Circuit should be open
    assert breaker.state == CircuitState.OPEN

    # Calls should be rejected
    with pytest.raises(CircuitBreakerError):
        breaker.call(lambda: "test")


def test_circuit_breaker_half_open():
    """Test circuit breaker transitions to half-open."""
    breaker = CircuitBreaker(failure_threshold=2, timeout=0)  # Immediate timeout

    # Trigger failures to open circuit
    for i in range(2):
        try:
            breaker.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

    assert breaker.state == CircuitState.OPEN

    # After timeout, should transition to half-open
    import time

    time.sleep(0.1)

    # First call should transition to half-open
    try:
        breaker.call(lambda: "test")
    except CircuitBreakerError:
        pass

    assert breaker.state == CircuitState.HALF_OPEN


def test_circuit_breaker_recovery():
    """Test circuit breaker recovery."""
    breaker = CircuitBreaker(
        failure_threshold=2, timeout=0, half_open_max_calls=2
    )

    # Open the circuit
    for i in range(2):
        try:
            breaker.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

    assert breaker.state == CircuitState.OPEN

    # Wait for timeout
    import time

    time.sleep(0.1)

    # Successful calls should close circuit
    for i in range(2):
        try:
            result = breaker.call(lambda: "success")
        except CircuitBreakerError:
            pass

    # Circuit should be closed
    assert breaker.state == CircuitState.CLOSED


def test_circuit_breaker_reset():
    """Test manual circuit breaker reset."""
    breaker = CircuitBreaker(failure_threshold=2)

    # Open the circuit
    for i in range(2):
        try:
            breaker.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

    assert breaker.state == CircuitState.OPEN

    # Reset
    breaker.reset()

    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_async_circuit_breaker():
    """Test async circuit breaker."""
    breaker = CircuitBreaker(failure_threshold=2)

    # Successful async call
    async def async_success():
        return "success"

    result = await breaker.async_call(async_success)
    assert result == "success"

    # Failed async calls
    async def async_failure():
        raise ValueError("Test error")

    for i in range(2):
        try:
            await breaker.async_call(async_failure)
        except ValueError:
            pass

    assert breaker.state == CircuitState.OPEN
