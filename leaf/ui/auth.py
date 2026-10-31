"""Optional password for the web interface, for when it runs somewhere others can reach it.

Set LEAF_UI_PASSWORD and every page, and NiceGUI's live connection, sits
behind a /login form with a single password field. After logging in the
browser gets a signed session cookie. Unset, the interface stays open.

Plain ASGI middleware, so it also covers NiceGUI's websocket.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import secrets
import time
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import cast, final
from urllib.parse import parse_qs, quote

from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from leaf.utility.logger.logger_utils import get_logger

logger = get_logger(__name__, log_file="interface.log")

PASSWORD_ENV = "LEAF_UI_PASSWORD"
LOGIN_PATH = "/login"
COOKIE_NAME = "leaf_session"
SESSION_SECONDS = 30 * 24 * 3600
MAX_FORM_BYTES = 4096

ICON_B64 = base64.b64encode((Path(__file__).parent / "images" / "icon.svg").read_bytes()).decode()

# Plain HTML, not NiceGUI: a NiceGUI page would need its websocket open before
# login, and password managers only recognise a real form submit. Colours and
# header follow styles.css and components/header.py. The hidden username field
# lets password managers save and fill the password.
LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LEAF login</title>
<link rel="icon" href="data:image/svg+xml;base64,{icon}">
<style>
:root {{ --bg: #f9fafb; --card: #ffffff; --border: rgba(229, 231, 235, .8); --text: #374151; --muted: #6b7280;
  --input-border: #d1d5db; --orange: #f15b25; --orange-dark: #d14e1e; --error: #ef4444; --error-bg: #fef2f2; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #111827; --card: #1f2937; --border: #374151; --text: #e5e7eb; --muted: #9ca3af;
    --input-border: #4b5563; --error-bg: #3b1d1d; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: flex; flex-direction: column; background: var(--bg); color: var(--text);
  font-family: Roboto, -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif; }}
header {{ background: #1c1c1c; color: #fff; padding: 16px; display: flex; align-items: center; gap: 12px; }}
header strong {{ font-size: 1.875rem; }}
header span {{ font-size: .875rem; opacity: .8; margin-left: 8px; }}
main {{ flex: 1; display: grid; place-items: center; padding: 16px; }}
form {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 8px 32px rgba(0, 0, 0, .1);
  padding: 2rem; width: min(22rem, 100%); display: grid; gap: .75rem; }}
form img {{ justify-self: center; }}
h1 {{ margin: 0 0 .25rem; font-size: 1.25rem; text-align: center; }}
label {{ font-size: .875rem; color: var(--muted); }}
input {{ font: inherit; padding: .65rem .75rem; border: 1px solid var(--input-border); border-radius: 6px;
  background: var(--card); color: var(--text); }}
input:focus {{ outline: 2px solid var(--orange); outline-offset: -1px; border-color: var(--orange); }}
button {{ font: inherit; font-weight: 500; letter-spacing: .02em; color: #fff; border: 0; border-radius: 6px; padding: .7rem;
  margin-top: .5rem; cursor: pointer; background: linear-gradient(135deg, var(--orange) 0%, var(--orange-dark) 100%); }}
button:hover {{ filter: brightness(1.08); }}
.error {{ margin: 0; padding: .5rem .75rem; border-radius: 6px; color: var(--error); background: var(--error-bg); font-size: .875rem; }}
@media (max-width: 600px) {{ header span {{ display: none; }} }}
</style></head>
<body>
<header><img width="32" height="32" alt="" src="data:image/svg+xml;base64,{icon}"><strong>LEAF</strong>
<span>Lightweight Equipment Adapter Framework</span></header>
<main><form method="post" action="{action}">
<img width="64" height="64" alt="" src="data:image/svg+xml;base64,{icon}">
<h1>Log in to LEAF</h1>
{error}
<input type="text" name="username" value="leaf" autocomplete="username" hidden>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<input type="hidden" name="next" value="{next}">
<button type="submit">Log in</button>
</form></main></body></html>
"""


def password_from_env() -> str | None:
    password = os.environ.get(PASSWORD_ENV, "")
    if password:
        return password
    return None


def require_password(app: Starlette) -> None:
    """Put the web interface behind the login form when LEAF_UI_PASSWORD is set."""
    password = password_from_env()
    if password is None:
        return
    app.add_middleware(PasswordMiddleware, password=password)
    logger.info("Web interface requires the LEAF_UI_PASSWORD login.")


def _safe_next(target: str) -> str:
    # Only same-site paths, so the login can't redirect to another site.
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


@final
class PasswordMiddleware:
    def __init__(self, app: ASGIApp, password: str) -> None:
        self.app: ASGIApp = app
        self._password: bytes = password.encode()
        # Derived from the password, so changing it logs every browser out.
        self._cookie_key: bytes = hashlib.sha256(b"leaf-ui-session\0" + self._password).digest()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope["path"] == LOGIN_PATH:
            await self._login(scope, receive, send)
            return
        if self._has_session(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Closing before accepting makes the server answer the handshake with 403.
            await send({"type": "websocket.close", "code": 1008})
            return
        target = cast(str, scope["path"])
        query_string = _query_string(scope)
        if query_string:
            target += "?" + query_string
        await _respond(send, 303, [(b"location", f"{LOGIN_PATH}?next={quote(target)}".encode())])

    async def _login(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] == "POST":
            form = parse_qs((await _read_body(receive)).decode("utf-8", "replace"))
            target = _safe_next(form.get("next", [""])[0])
            if secrets.compare_digest(form.get("password", [""])[0].encode(), self._password):
                await _respond(
                    send,
                    303,
                    [(b"location", target.encode()), (b"set-cookie", self._session_cookie(scope).encode())],
                )
                return
            await self._login_page(send, target, 401, "Wrong password.")
            return
        query = parse_qs(_query_string(scope))
        await self._login_page(send, _safe_next(query.get("next", [""])[0]), 200, "")

    async def _login_page(self, send: Send, target: str, status: int, error: str) -> None:
        error_html = ""
        if error:
            error_html = f'<p class="error">{html.escape(error)}</p>'
        body = LOGIN_PAGE.format(action=LOGIN_PATH, error=error_html, next=html.escape(target), icon=ICON_B64)
        await _respond(send, status, [(b"content-type", b"text/html; charset=utf-8")], body.encode())

    def _sign(self, expires: str) -> str:
        return hmac.new(self._cookie_key, expires.encode(), hashlib.sha256).hexdigest()

    def _session_cookie(self, scope: Scope) -> str:
        expires = str(int(time.time()) + SESSION_SECONDS)
        cookie = (
            f"{COOKIE_NAME}={expires}.{self._sign(expires)}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; SameSite=Lax"
        )
        # Behind an ingress the app sees plain http, so trust its forwarded scheme.
        if scope.get("scheme") == "https" or _header(scope, b"x-forwarded-proto") == b"https":
            cookie += "; Secure"
        return cookie

    def _has_session(self, scope: Scope) -> bool:
        cookies: SimpleCookie = SimpleCookie()
        try:
            cookies.load(_header(scope, b"cookie").decode("latin-1"))
        except CookieError:
            return False
        if COOKIE_NAME not in cookies:
            return False
        expires, _, signature = cookies[COOKIE_NAME].value.partition(".")
        if not expires.isdigit() or not hmac.compare_digest(signature, self._sign(expires)):
            return False
        return int(expires) > time.time()


def _header(scope: Scope, name: bytes) -> bytes:
    headers = cast(list[tuple[bytes, bytes]], scope["headers"])
    return dict(headers).get(name, b"")


def _query_string(scope: Scope) -> str:
    return cast(bytes, scope.get("query_string", b"")).decode("latin-1")


async def _read_body(receive: Receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += cast(bytes, message.get("body", b""))
        if len(body) > MAX_FORM_BYTES or not cast(bool, message.get("more_body", False)):
            return body[:MAX_FORM_BYTES]


async def _respond(send: Send, status: int, headers: list[tuple[bytes, bytes]], body: bytes = b"") -> None:
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
