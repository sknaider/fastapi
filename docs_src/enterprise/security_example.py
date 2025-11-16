"""
Security-focused FastAPI Application Example.

Demonstrates enterprise security features:
- Security headers
- Rate limiting
- Audit logging
"""

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.security_headers import StrictSecurityHeadersMiddleware
from fastapi.middleware.rate_limit import RateLimitMiddleware
from fastapi.middleware.audit import (
    AuditLoggingMiddleware,
    AuditEventType,
    get_audit_logger,
)

app = FastAPI(title="Secure API", version="1.0.0")

# Add strict security headers
app.add_middleware(StrictSecurityHeadersMiddleware)

# Add aggressive rate limiting
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=30,  # Strict limit
    requests_per_hour=500,
)

# Add audit logging
app.add_middleware(AuditLoggingMiddleware)

# OAuth2 setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# Mock user database
USERS_DB = {
    "admin": {
        "username": "admin",
        "email": "admin@example.com",
        "hashed_password": "fakehashed_secret",
    }
}


def verify_token(token: str = Depends(oauth2_scheme)):
    """Verify JWT token (simplified example)."""
    audit_logger = get_audit_logger()

    if token != "valid_token":
        audit_logger.log(
            event_type=AuditEventType.LOGIN_FAILURE,
            actor="unknown",
            result="failure",
            details={"reason": "Invalid token"},
        )
        raise HTTPException(status_code=401, detail="Invalid token")

    audit_logger.log(
        event_type=AuditEventType.LOGIN_SUCCESS,
        actor="admin@example.com",
        result="success",
    )

    return USERS_DB["admin"]


@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint."""
    audit_logger = get_audit_logger()

    # Verify credentials (simplified)
    if form_data.username != "admin" or form_data.password != "secret":
        audit_logger.log(
            event_type=AuditEventType.LOGIN_FAILURE,
            actor=form_data.username,
            result="failure",
            details={"reason": "Invalid credentials"},
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    audit_logger.log(
        event_type=AuditEventType.LOGIN_SUCCESS,
        actor=form_data.username,
        result="success",
    )

    return {"access_token": "valid_token", "token_type": "bearer"}


@app.get("/api/sensitive-data")
async def get_sensitive_data(current_user: dict = Depends(verify_token)):
    """
    Protected endpoint requiring authentication.

    All access is audited.
    """
    audit_logger = get_audit_logger()

    audit_logger.log(
        event_type=AuditEventType.DATA_READ,
        actor=current_user["email"],
        resource="sensitive-data",
        action="READ",
    )

    return {
        "data": "Sensitive information",
        "user": current_user["email"],
    }


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(verify_token)):
    """
    Admin endpoint to delete user.

    Deletion is audited for compliance.
    """
    audit_logger = get_audit_logger()

    audit_logger.log(
        event_type=AuditEventType.USER_DELETED,
        actor=current_user["email"],
        resource=f"users/{user_id}",
        action="DELETE",
        details={"user_id": user_id},
    )

    return {"message": f"User {user_id} deleted"}
