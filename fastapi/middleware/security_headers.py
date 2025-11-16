"""
Security Headers Middleware for FastAPI.

Implements enterprise-grade security headers including:
- Content Security Policy (CSP)
- X-Frame-Options
- X-Content-Type-Options
- Strict-Transport-Security (HSTS)
- Referrer-Policy
- Permissions-Policy
- X-XSS-Protection (legacy)
"""

from typing import Callable, Optional

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """
    Middleware to add security headers to all responses.

    Example:
        ```python
        from fastapi import FastAPI
        from fastapi.middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)
        ```

    Args:
        app: The ASGI application
        csp: Content Security Policy directive
        hsts_max_age: HSTS max-age in seconds (default: 31536000 = 1 year)
        hsts_include_subdomains: Include subdomains in HSTS
        hsts_preload: Enable HSTS preload
        frame_options: X-Frame-Options value (DENY, SAMEORIGIN, or None to disable)
        content_type_options: Set X-Content-Type-Options: nosniff
        referrer_policy: Referrer-Policy value
        permissions_policy: Permissions-Policy directive
        xss_protection: Enable X-XSS-Protection (legacy, for old browsers)
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        csp: Optional[str] = "default-src 'self'",
        hsts_max_age: int = 31536000,
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = True,
        frame_options: Optional[str] = "DENY",
        content_type_options: bool = True,
        referrer_policy: str = "strict-origin-when-cross-origin",
        permissions_policy: Optional[str] = None,
        xss_protection: bool = True,
    ) -> None:
        self.app = app
        self.csp = csp
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload
        self.frame_options = frame_options
        self.content_type_options = content_type_options
        self.referrer_policy = referrer_policy
        self.permissions_policy = permissions_policy
        self.xss_protection = xss_protection

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)

                # Content Security Policy
                if self.csp and "content-security-policy" not in headers:
                    headers["Content-Security-Policy"] = self.csp

                # HTTP Strict Transport Security
                if self.hsts_max_age > 0:
                    hsts_value = f"max-age={self.hsts_max_age}"
                    if self.hsts_include_subdomains:
                        hsts_value += "; includeSubDomains"
                    if self.hsts_preload:
                        hsts_value += "; preload"
                    headers["Strict-Transport-Security"] = hsts_value

                # X-Frame-Options
                if self.frame_options and "x-frame-options" not in headers:
                    headers["X-Frame-Options"] = self.frame_options

                # X-Content-Type-Options
                if self.content_type_options and "x-content-type-options" not in headers:
                    headers["X-Content-Type-Options"] = "nosniff"

                # Referrer-Policy
                if self.referrer_policy and "referrer-policy" not in headers:
                    headers["Referrer-Policy"] = self.referrer_policy

                # Permissions-Policy
                if self.permissions_policy and "permissions-policy" not in headers:
                    headers["Permissions-Policy"] = self.permissions_policy

                # X-XSS-Protection (legacy, for old browsers)
                if self.xss_protection and "x-xss-protection" not in headers:
                    headers["X-XSS-Protection"] = "1; mode=block"

            await send(message)

        await self.app(scope, receive, send_with_headers)


class StrictSecurityHeadersMiddleware(SecurityHeadersMiddleware):
    """
    Middleware with strict security headers for production environments.

    This uses very restrictive defaults suitable for high-security applications.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        csp: Optional[str] = "default-src 'none'; script-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        **kwargs,
    ) -> None:
        super().__init__(app, csp=csp, **kwargs)
