from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.core.auth import SESSION_COOKIE, api_key_matches, create_session_token, verify_session_token
from app.core.config import get_settings

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    api_key: str


@router.get("/api/auth/session")
async def session_status(request: Request) -> dict[str, bool]:
    settings = get_settings()
    authenticated = not settings.auth_enabled or verify_session_token(
        request.cookies.get(SESSION_COOKIE)
    )
    return {"auth_enabled": settings.auth_enabled, "authenticated": authenticated}


@router.post("/api/auth/session")
async def create_session(payload: LoginRequest, request: Request, response: Response) -> dict[str, bool]:
    settings = get_settings()
    if settings.auth_enabled and not api_key_matches(payload.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
    if settings.auth_enabled:
        secure_cookie = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https"
        )
        response.set_cookie(
            SESSION_COOKIE,
            create_session_token(),
            max_age=settings.auth_session_ttl_seconds,
            httponly=True,
            secure=secure_cookie,
            samesite="strict",
            path="/",
        )
    return {"auth_enabled": settings.auth_enabled, "authenticated": True}


@router.delete("/api/auth/session")
async def delete_session(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"auth_enabled": get_settings().auth_enabled, "authenticated": False}
