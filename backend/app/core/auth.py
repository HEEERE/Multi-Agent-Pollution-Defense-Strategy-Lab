"""API-key authentication with stateless signed browser sessions."""

import hashlib
import hmac
import time

from fastapi import HTTPException, Request, WebSocket, status

from app.core.config import get_settings

SESSION_COOKIE = "majd_session"


def api_key_matches(candidate: str) -> bool:
    expected = get_settings().majd_api_key
    return bool(expected) and hmac.compare_digest(candidate, expected)


def create_session_token() -> str:
    settings = get_settings()
    expires_at = int(time.time()) + settings.auth_session_ttl_seconds
    payload = str(expires_at)
    signature = hmac.new(
        settings.majd_api_key.encode("utf-8"),
        f"majd-session:{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires_raw, signature = token.split(".", 1)
    try:
        if int(expires_raw) <= int(time.time()):
            return False
    except ValueError:
        return False
    settings = get_settings()
    expected = hmac.new(
        settings.majd_api_key.encode("utf-8"),
        f"majd-session:{expires_raw}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _bearer_value(header: str | None) -> str:
    if not header:
        return ""
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


async def require_api_auth(request: Request) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return
    candidate = request.headers.get("x-api-key", "") or _bearer_value(
        request.headers.get("authorization")
    )
    if api_key_matches(candidate) or verify_session_token(
        request.cookies.get(SESSION_COOKIE)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def websocket_is_authenticated(websocket: WebSocket) -> bool:
    settings = get_settings()
    if not settings.auth_enabled:
        return True
    candidate = websocket.headers.get("x-api-key", "") or _bearer_value(
        websocket.headers.get("authorization")
    )
    return api_key_matches(candidate) or verify_session_token(
        websocket.cookies.get(SESSION_COOKIE)
    )
