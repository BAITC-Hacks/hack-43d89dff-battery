"""Dependency-free HTTP API and frontend for the marketplace MVP.

Run with: ``python3 -m backend.api``
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import OrderedDict, deque
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .auth import AuthService, SESSION_TTL_SECONDS, csrf_matches
from .database import Database
from .service import MarketplaceService, ServiceError


MAX_BODY_BYTES = 1_000_000
SESSION_COOKIE = "sana_session"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
# Only application assets are public. Never expose repository files, databases,
# credentials, or arbitrary paths through the static-file route.
FRONTEND_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/api.js": ("api.js", "text/javascript; charset=utf-8"),
    "/auth.js": ("auth.js", "text/javascript; charset=utf-8"),
    "/workspace.js": ("workspace.js", "text/javascript; charset=utf-8"),
    "/examples.js": ("examples.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
TASK_ROUTE = re.compile(r"^/api/tasks/([^/]+)$")
TASK_ANSWERS_ROUTE = re.compile(r"^/api/tasks/([^/]+)/answers$")
TASK_CARD_ROUTE = re.compile(r"^/api/tasks/([^/]+)/card$")
TASK_CONFIRM_ROUTE = re.compile(r"^/api/tasks/([^/]+)/confirm$")
TASK_PUBLISH_ROUTE = re.compile(r"^/api/tasks/([^/]+)/publish$")
TASK_PROPOSALS_ROUTE = re.compile(r"^/api/tasks/([^/]+)/proposals$")
BUSINESS_TASKS_ROUTE = re.compile(r"^/api/businesses/([^/]+)/tasks$")
TEAM_PROPOSALS_ROUTE = re.compile(r"^/api/teams/([^/]+)/proposals$")
CATALOG_TASK_ROUTE = re.compile(r"^/api/catalog/([^/]+)$")
PROPOSAL_DECISION_ROUTE = re.compile(r"^/api/proposals/([^/]+)/decision$")


class AuthAttemptLimiter:
    """Bounded, synchronized process-local throttling by remote client address."""

    def __init__(self, limit: int = 20, window: int = 60, max_clients: int = 2048) -> None:
        self.limit = limit
        self.window = window
        self.max_clients = max_clients
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def consume(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts.pop(client, deque())
            while attempts and attempts[0] <= now - self.window:
                attempts.popleft()
            if len(self._attempts) >= self.max_clients:
                self._attempts.popitem(last=False)
            self._attempts[client] = attempts
            if len(attempts) >= self.limit:
                raise ServiceError(429, "auth_rate_limited", "Too many sign-in attempts. Please wait a minute and try again.")
            attempts.append(now)


class MarketplaceHandler(BaseHTTPRequestHandler):
    """Routes the small REST surface to ``MarketplaceService``."""

    service: MarketplaceService
    auth_service: AuthService | None = None
    auth_limiter = AuthAttemptLimiter()
    server_version = "TaskMarketplace/1.0"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch("OPTIONS")

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        self._response_cookie = None
        self._request_principal = None
        self._session_token = None
        try:
            if method == "OPTIONS":
                self._require_origin()
                self._send(HTTPStatus.NO_CONTENT, None)
                return
            if method == "GET" and path in FRONTEND_ASSETS:
                self._send_asset(path)
                return
            self._session_token = self._read_session_cookie()
            if self._session_token:
                self._request_principal = self._auth().authenticate(self._session_token)
            if method in {"POST", "PATCH"}:
                self._require_origin()
                if self.headers.get_content_type() != "application/json":
                    raise ServiceError(415, "json_required", "Use Content-Type: application/json.")
                if self._request_principal and not csrf_matches(self._session_token, self.headers.get("X-CSRF-Token")):
                    raise ServiceError(403, "invalid_csrf_token", "Your session could not be verified. Refresh the page and try again.")
            result, status = self._route(method, path, query)
            self._send(status, result)
        except ServiceError as error:
            self._send(error.status, {"error": {"code": error.code, "message": error.message}})
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": {"code": "invalid_json", "message": "Request body must be valid JSON."}})
        except ValueError as error:
            self._send(422, {"error": {"code": "validation_error", "message": str(error)}})
        except Exception:
            # Deliberately do not leak internals or configuration through the API.
            self.log_error("Unhandled API error")
            self._send(500, {"error": {"code": "internal_error", "message": "Unexpected server error."}})

    def _auth(self) -> AuthService:
        return self.auth_service or AuthService(self.service.database)

    def _require_principal(self):
        if self._request_principal is None:
            raise ServiceError(401, "authentication_required", "Sign in to continue.")
        return self._request_principal

    def _read_session_cookie(self) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel and morsel.value else None

    def _set_session_cookie(self, token: str | None) -> None:
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE] = token or ""
        morsel = cookie[SESSION_COOKIE]
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        morsel["path"] = "/"
        morsel["max-age"] = SESSION_TTL_SECONDS if token else 0
        if not token:
            morsel["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        if os.getenv("MARKETPLACE_COOKIE_SECURE") == "1":
            morsel["secure"] = True
        self._response_cookie = morsel.OutputString()

    def _approved_origin(self) -> str | None:
        origins = self.headers.get_all("Origin", [])
        if len(origins) != 1 or not _valid_origin(origins[0]):
            return None
        origin = origins[0]
        scheme = "https" if os.getenv("MARKETPLACE_COOKIE_SECURE") == "1" else "http"
        same_origin = f"{scheme}://{self.headers.get('Host', '')}"
        configured_origin = os.getenv("CORS_ORIGIN", "")
        if origin == same_origin or (_valid_origin(configured_origin) and origin == configured_origin):
            return origin
        return None

    def _require_origin(self) -> None:
        if self._approved_origin() is None:
            raise ServiceError(403, "origin_not_allowed", "This request must come from the marketplace website.")

    def _send_asset(self, path: str) -> None:
        filename, content_type = FRONTEND_ASSETS[path]
        asset = (FRONTEND_DIR / filename).resolve()
        if asset.parent != FRONTEND_DIR.resolve() or not asset.is_file():
            raise ServiceError(404, "route_not_found", "Asset not found.")
        body = asset.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _route(self, method: str, path: str, query: dict[str, list[str]]) -> tuple[Any, int]:
        if method == "GET" and path == "/health":
            return {"status": "ok"}, 200
        if path == "/api/auth/session" and method == "GET":
            session = self._auth().session(self._session_token)
            if self._session_token and not session["user"]:
                self._set_session_cookie(None)
            return session, 200
        if path in {"/api/auth/register", "/api/auth/login"} and method == "POST":
            self.auth_limiter.consume(self.client_address[0])
            action = self._auth().register if path.endswith("/register") else self._auth().login
            session, token = action(self._body())
            self._set_session_cookie(token)
            return session, 201 if path.endswith("/register") else 200
        if path == "/api/auth/logout" and method == "POST":
            self._auth().logout(self._session_token)
            self._set_session_cookie(None)
            return self._auth().session(None), 200
        if method == "GET" and path == "/api/meta/readiness":
            return {
                "levels": {
                    "draft": "0-39",
                    "working": "40-69",
                    "ready": "70-89",
                    "priority": "90-100",
                },
                "weights": {
                    "context_and_business_need": 20,
                    "data_and_materials": 20,
                    "expected_result": 15,
                    "success_criteria": 15,
                    "limitations": 10,
                    "target_users": 10,
                    "contact_and_interaction": 10,
                },
            }, 200
        if method == "POST" and path in {"/api/businesses", "/api/teams"}:
            raise ServiceError(410, "registration_required", "Create an account through /api/auth/register.")
        if method == "POST" and path == "/api/tasks":
            principal = self._require_principal()
            return self.service.create_task(self._body(), principal), 201
        if method == "GET" and path == "/api/catalog":
            return self.service.catalog(
                tags=_csv_values(query.get("tags", [])),
                industry=_one(query, "industry"),
                readiness=_one(query, "readiness"),
                minimum_score=_integer_query(query, "min_score", 0),
                query=_one(query, "q"),
                limit=_integer_query(query, "limit", 50),
                offset=_integer_query(query, "offset", 0),
            ), 200

        if match := TASK_ROUTE.match(path):
            if method == "GET":
                return self.service.get_task(match.group(1), self._request_principal), 200
        if match := TASK_ANSWERS_ROUTE.match(path):
            if method == "POST":
                principal = self._require_principal()
                return self.service.submit_answers(match.group(1), self._body(), principal), 200
        if match := TASK_CARD_ROUTE.match(path):
            if method == "PATCH":
                principal = self._require_principal()
                return self.service.update_card(match.group(1), self._body(), principal), 200
        if match := TASK_CONFIRM_ROUTE.match(path):
            if method == "POST":
                return self.service.confirm_task(match.group(1), self._require_principal()), 200
        if match := TASK_PUBLISH_ROUTE.match(path):
            if method == "POST":
                return self.service.publish_task(match.group(1), self._require_principal()), 200
        if match := TASK_PROPOSALS_ROUTE.match(path):
            if method == "POST":
                principal = self._require_principal()
                return self.service.create_proposal(match.group(1), self._body(), principal), 201
            if method == "GET":
                return self.service.list_task_proposals(match.group(1), self._require_principal()), 200
        if match := BUSINESS_TASKS_ROUTE.match(path):
            if method == "GET":
                return self.service.list_business_tasks(match.group(1), self._require_principal()), 200
        if match := TEAM_PROPOSALS_ROUTE.match(path):
            if method == "GET":
                return self.service.list_team_proposals(match.group(1), self._require_principal()), 200
        if match := CATALOG_TASK_ROUTE.match(path):
            if method == "GET":
                return self.service.get_task(match.group(1)), 200
        if match := PROPOSAL_DECISION_ROUTE.match(path):
            if method == "PATCH":
                principal = self._require_principal()
                body = self._body()
                return self.service.decide_proposal(match.group(1), body.get("decision"), principal), 200
        raise ServiceError(404, "route_not_found", "Route not found.")

    def _body(self) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ServiceError(411, "content_length_required", "Content-Length is required.")
        try:
            length = int(content_length)
        except ValueError as error:
            raise ServiceError(400, "invalid_content_length", "Invalid Content-Length.") from error
        if length < 0 or length > MAX_BODY_BYTES:
            raise ServiceError(413, "payload_too_large", "Request body exceeds 1 MB.")
        raw = self.rfile.read(length)
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict):
            raise ServiceError(422, "validation_error", "Request JSON must be an object.")
        return body

    def _send(self, status: int | HTTPStatus, payload: Any) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        origin = self._approved_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        if self._response_cookie:
            self.send_header("Set-Cookie", self._response_cookie)
        if int(status) == 429:
            self.send_header("Retry-After", str(self.auth_limiter.window))
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep normal API use quiet; errors remain visible through log_error.
        return


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    database_path: str | Path | None = None,
    service: MarketplaceService | None = None,
) -> ThreadingHTTPServer:
    if service is None:
        path = database_path or os.getenv("MARKETPLACE_DB_PATH", "data/marketplace.sqlite3")
        service = MarketplaceService(Database(path))
    service.initialize()
    handler = type("ConfiguredMarketplaceHandler", (MarketplaceHandler,), {
        "service": service, "auth_service": AuthService(service.database),
    })
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    host = os.getenv("MARKETPLACE_HOST", "127.0.0.1")
    port = int(os.getenv("MARKETPLACE_PORT", "8000"))
    server = create_server(host, port)
    print(f"Marketplace website and API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _one(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[-1] if values else None


def _integer_query(query: dict[str, list[str]], name: str, default: int) -> int:
    value = _one(query, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ServiceError(422, "invalid_query", f"{name} must be an integer") from error


def _csv_values(values: list[str]) -> list[str]:
    return [item.strip() for value in values for item in value.split(",") if item.strip()]


def _valid_origin(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return bool(
            parsed.scheme in {"http", "https"} and parsed.hostname
            and not parsed.username and not parsed.password
            and not parsed.path and not parsed.query and not parsed.fragment
            and parsed.port != 0 and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


if __name__ == "__main__":
    main()
