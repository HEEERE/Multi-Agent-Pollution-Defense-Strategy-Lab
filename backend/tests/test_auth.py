import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.routes import auth, websocket
from app.core.auth import require_api_auth
from app.core.config import get_settings


@pytest.fixture
def authenticated_app(monkeypatch):
    monkeypatch.setenv("MAJD_API_KEY", "test-access-key")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(websocket.router)

    @app.get("/protected", dependencies=[Depends(require_api_auth)])
    async def protected():
        return {"ok": True}

    try:
        yield app
    finally:
        get_settings.cache_clear()


def test_api_key_and_signed_browser_session_authenticate(authenticated_app):
    with TestClient(authenticated_app) as client:
        assert client.get("/protected").status_code == 401
        assert client.get(
            "/protected", headers={"Authorization": "Bearer test-access-key"}
        ).status_code == 200
        assert client.post(
            "/api/auth/session", json={"api_key": "wrong"}
        ).status_code == 401

        login = client.post(
            "/api/auth/session", json={"api_key": "test-access-key"}
        )
        assert login.status_code == 200
        assert login.json()["authenticated"] is True
        assert "HttpOnly" in login.headers["set-cookie"]
        assert client.get("/protected").status_code == 200


def test_websocket_requires_authenticated_session(authenticated_app):
    with TestClient(authenticated_app) as anonymous:
        with pytest.raises(WebSocketDisconnect) as exc:
            with anonymous.websocket_connect("/ws/events"):
                pass
        assert exc.value.code == 4401

    with TestClient(authenticated_app) as client:
        client.post("/api/auth/session", json={"api_key": "test-access-key"})
        with client.websocket_connect("/ws/events") as socket:
            message = socket.receive_json()
            assert message["source_node"] == "Backend"
