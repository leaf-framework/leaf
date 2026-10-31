from typing import cast

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from leaf.ui.auth import PasswordMiddleware, password_from_env


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/")
    def index() -> dict[str, str]:
        return {"page": "index"}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app.add_middleware(PasswordMiddleware, password="s3cret")
    return TestClient(app)


def test_pages_redirect_to_login(client: httpx.Client) -> None:
    resp = client.get("/?tab=logs", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/%3Ftab%3Dlogs"

    page = client.get(resp.headers["location"])
    assert page.status_code == 200
    assert 'autocomplete="current-password"' in page.text
    assert 'value="/?tab=logs"' in page.text


def test_websocket_needs_session(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            _ = ws.receive_text()


def test_right_password_sets_session(client: TestClient) -> None:
    # Starlette leaves TestClient's HTTP methods untyped; httpx.Client has them.
    http = cast(httpx.Client, client)
    resp = http.post("/login", data={"password": "s3cret", "next": "/"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "HttpOnly" in resp.headers["set-cookie"]

    assert http.get("/", follow_redirects=False).status_code == 200
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_text() == "hi"


def test_wrong_password_is_rejected(client: httpx.Client) -> None:
    resp = client.post("/login", data={"password": "wrong", "next": "/"})
    assert resp.status_code == 401
    assert "Wrong password" in resp.text
    assert "set-cookie" not in resp.headers
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_only_redirects_within_the_site(client: httpx.Client) -> None:
    for target in ("https://evil.example", "//evil.example", "/\\evil.example"):
        resp = client.post("/login", data={"password": "s3cret", "next": target}, follow_redirects=False)
        assert resp.headers["location"] == "/"


def test_forged_or_extended_session_is_rejected(client: httpx.Client) -> None:
    client.cookies.set("leaf_session", "9999999999.deadbeef")
    assert client.get("/", follow_redirects=False).status_code == 303

    client.cookies.clear()
    _ = client.post("/login", data={"password": "s3cret"})
    expires, _, signature = client.cookies["leaf_session"].partition(".")
    # A later expiry with the old signature: extending a session needs the key.
    client.cookies.clear()
    client.cookies.set("leaf_session", f"{int(expires) + 1}.{signature}")
    assert client.get("/", follow_redirects=False).status_code == 303


def test_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEAF_UI_PASSWORD", raising=False)
    assert password_from_env() is None
    monkeypatch.setenv("LEAF_UI_PASSWORD", "")
    assert password_from_env() is None
    monkeypatch.setenv("LEAF_UI_PASSWORD", "pw")
    assert password_from_env() == "pw"
