"""Exercise real HTTP parsing and dispatch without requiring a local port."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import AuthAttemptLimiter, FRONTEND_ASSETS, FRONTEND_DIR, MarketplaceHandler
from backend.auth import AuthService
from backend.database import Database
from backend.service import MarketplaceService


class MemoryConnection:
    def __init__(self, request):
        self.request = io.BytesIO(request)
        self.response = bytearray()

    def makefile(self, mode, buffering=None):
        return self.request

    def sendall(self, data):
        self.response.extend(data)


class MarketplaceHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = MarketplaceService(
            Database(Path(self.temp_dir.name) / "http.sqlite3"), ai_mode="offline"
        )
        self.service.initialize()
        self.auth = AuthService(self.service.database)
        self.handler = type("TestMarketplaceHandler", (MarketplaceHandler,), {
            "service": self.service, "auth_service": self.auth, "auth_limiter": AuthAttemptLimiter(),
        })
        self.environment = patch.dict(os.environ, {"MARKETPLACE_COOKIE_SECURE": "0", "CORS_ORIGIN": ""})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, session=None, *, origin="http://localhost", headers=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = {"Host": "localhost", "Connection": "close"}
        if origin is not None:
            request_headers["Origin"] = origin
        if session:
            request_headers["Cookie"] = session["cookie"]
            if method in {"POST", "PATCH"}:
                request_headers["X-CSRF-Token"] = session["data"]["csrf_token"]
        if payload is not None:
            request_headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        for key, value in (headers or {}).items():
            if value is None:
                request_headers.pop(key, None)
            else:
                request_headers[key] = value
        lines = [f"{method} {path} HTTP/1.1"] + [f"{key}: {value}" for key, value in request_headers.items()]
        connection = MemoryConnection("\r\n".join(lines).encode() + b"\r\n\r\n" + body)
        self.handler(connection, ("127.0.0.1", 0), object())
        raw_headers, result = bytes(connection.response).split(b"\r\n\r\n", 1)
        lines = raw_headers.decode().split("\r\n")
        status = int(lines[0].split()[1])
        response_headers = dict(line.split(": ", 1) for line in lines[1:])
        if response_headers.get("Content-Type", "").startswith("application/json"):
            result = json.loads(result)
        return status, response_headers, result

    def register(self, role="business", email="owner@example.test"):
        status, headers, data = self.request("POST", "/api/auth/register", {
            "role": role, "name": "HTTP user", "email": email, "password": "Correct-horse-battery-73!",
            "organization_name": "HTTP business", "team_name": "HTTP team",
        })
        self.assertEqual(status, 201)
        return {"cookie": headers["Set-Cookie"].split(";", 1)[0], "data": data}, headers

    def test_frontend_assets_share_the_api_origin(self):
        for path, (filename, content_type) in FRONTEND_ASSETS.items():
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], content_type)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(body, (FRONTEND_DIR / filename).read_bytes())
        self.assertIn("/auth.js", FRONTEND_ASSETS)
        self.assertEqual(self.request("GET", "/health")[2], {"status": "ok"})

    def test_static_routes_cannot_expose_repository_files(self):
        for path in ["/.env", "/agents.md", "/backend/auth.py", "/backend/api.py", "/../.env", "/%2e%2e/.env", "/frontend/index.html"]:
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(body["error"]["code"], "route_not_found")

    def test_cookie_session_is_safe_and_logout_revokes_access(self):
        status, headers, anonymous = self.request("GET", "/api/auth/session")
        self.assertEqual(status, 200)
        self.assertEqual(anonymous, {"user": None, "profile": None, "csrf_token": None, "expires_at": None})
        self.assertEqual(headers["Cache-Control"], "no-store")
        session, headers = self.register()
        cookie = headers["Set-Cookie"]
        for attribute in ["HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=604800"]:
            self.assertIn(attribute, cookie)
        self.assertNotIn("Secure", cookie)
        data = session["data"]
        self.assertEqual(data["user"]["role"], "business")
        self.assertEqual(data["profile"]["name"], "HTTP business")
        safe_response = json.dumps(data)
        self.assertTrue(session["cookie"].split("=", 1)[1] not in safe_response, "Raw session cookie must never appear in JSON")
        self.assertTrue(all(name not in safe_response for name in ["owner_token", "password_hash", "password_salt"]), "Session response must not contain credentials")
        self.assertEqual(self.request("GET", "/api/auth/session", session=session)[2], data)
        status, headers, logged_out = self.request("POST", "/api/auth/logout", {}, session)
        self.assertEqual(status, 200)
        self.assertIsNone(logged_out["user"])
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        profile_id = data["profile"]["id"]
        self.assertEqual(self.request("GET", f"/api/businesses/{profile_id}/tasks", session=session)[0], 401)
        status, headers, stale = self.request("GET", "/api/auth/session", session=session)
        self.assertIsNone(stale["user"])
        self.assertIn("Max-Age=0", headers["Set-Cookie"])

    def test_login_restores_profile_and_secure_cookie(self):
        session, _ = self.register("student")
        self.request("POST", "/api/auth/logout", {}, session)
        with patch.dict(os.environ, {"MARKETPLACE_COOKIE_SECURE": "1"}):
            status, headers, data = self.request("POST", "/api/auth/login", {
                "email": "owner@example.test", "password": "Correct-horse-battery-73!",
            }, origin="https://localhost")
        self.assertEqual(status, 200)
        self.assertEqual(data["profile"]["id"], session["data"]["profile"]["id"])
        self.assertIn("Secure", headers["Set-Cookie"])
        status, headers, body = self.request("POST", "/api/auth/login", {
            "email": "owner@example.test", "password": "Wrong-password-123!",
        })
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(body["error"]["code"], "invalid_credentials")

    def test_csrf_required_on_session_mutations_including_logout(self):
        session, _ = self.register()
        for path, payload in [
            ("/api/tasks", {"business_id": session["data"]["profile"]["id"], "initial_draft": "Improve support."}),
            ("/api/auth/logout", {}),
            ("/api/auth/login", {"email": "owner@example.test", "password": "Correct-horse-battery-73!"}),
        ]:
            for invalid in [None, "wrong-token"]:
                with self.subTest(path=path, csrf_present=invalid is not None):
                    status, _, body = self.request("POST", path, payload, session, headers={"X-CSRF-Token": invalid})
                    self.assertEqual(status, 403)
                    self.assertEqual(body["error"]["code"], "invalid_csrf_token")
        self.assertIsNotNone(self.request("GET", "/api/auth/session", session=session)[2]["user"])
        status, _, body = self.request("PATCH", "/api/tasks/unknown/card", {}, session, headers={"X-CSRF-Token": None})
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "invalid_csrf_token")

    def test_origin_json_and_cors_enforcement(self):
        for path in ["/api/auth/login", "/api/auth/register", "/api/tasks"]:
            for origin in [None, "null", "https://untrusted.example", "http://localhost.evil.test"]:
                with self.subTest(path=path, origin=origin):
                    status, headers, body = self.request("POST", path, {}, origin=origin)
                    self.assertEqual(status, 403)
                    self.assertEqual(body["error"]["code"], "origin_not_allowed")
                    self.assertNotIn("Access-Control-Allow-Origin", headers)
                    self.assertNotIn("Access-Control-Allow-Credentials", headers)
        status, _, body = self.request("POST", "/api/auth/login", {}, headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(body["error"]["code"], "json_required")
        with patch.dict(os.environ, {"CORS_ORIGIN": "*"}):
            self.assertEqual(self.request("OPTIONS", "/api/auth/login", origin="https://untrusted.example")[0], 403)
        with patch.dict(os.environ, {"CORS_ORIGIN": "https://trusted.example"}):
            status, headers, _ = self.request("OPTIONS", "/api/auth/login", origin="https://trusted.example")
            self.assertEqual(status, 204)
            self.assertEqual(headers["Access-Control-Allow-Origin"], "https://trusted.example")
            self.assertEqual(headers["Access-Control-Allow-Credentials"], "true")
            self.assertIn("X-CSRF-Token", headers["Access-Control-Allow-Headers"])
            self.assertNotIn("X-Owner-Token", headers["Access-Control-Allow-Headers"])
        _, headers, _ = self.request("GET", "/api/catalog", origin=None)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_legacy_http_identity_creation_and_owner_headers_are_disabled(self):
        for path in ["/api/businesses", "/api/teams"]:
            status, _, body = self.request("POST", path, {"name": "Old profile"})
            self.assertEqual(status, 410)
            self.assertEqual(body["error"]["code"], "registration_required")
        legacy = self.service.create_business({"name": "Legacy business"})
        headers = {"X-Owner-Token": legacy["owner_token"]}
        status, _, body = self.request("POST", "/api/tasks", {
            "business_id": legacy["id"], "initial_draft": "Improve support."
        }, headers=headers)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "authentication_required")
        self.assertEqual(self.request("GET", f"/api/businesses/{legacy['id']}/tasks", headers=headers)[0], 401)
        for path in ["/api/tasks/unknown/proposals", "/api/teams/unknown/proposals"]:
            self.assertEqual(self.request("GET", path)[0], 401)
        self.assertEqual(self.request("GET", "/api/catalog")[0], 200)

    def test_auth_attempts_are_limited_and_client_memory_is_bounded(self):
        self.handler.auth_limiter = AuthAttemptLimiter(limit=2, max_clients=2)
        for _ in range(2):
            self.request("POST", "/api/auth/login", {"email": "unknown@example.test", "password": "wrong"})
        status, headers, body = self.request("POST", "/api/auth/login", {})
        self.assertEqual(status, 429)
        self.assertEqual(body["error"]["code"], "auth_rate_limited")
        self.assertEqual(headers["Retry-After"], "60")
        self.handler.auth_limiter.consume("another-client")
        self.handler.auth_limiter.consume("third-client")
        self.assertEqual(len(self.handler.auth_limiter._attempts), 2)

    def test_complete_workflow_and_authorization_through_http(self):
        business, _ = self.register()
        business_id = business["data"]["profile"]["id"]
        status, _, task = self.request("POST", "/api/tasks", {
            "business_id": business_id, "initial_draft": "Improve how we prioritize support tickets."
        }, business)
        self.assertEqual(status, 201)
        self.assertGreaterEqual(len(task["clarifying_questions"]), 3)
        task_path = f"/api/tasks/{task['id']}"
        self.assertEqual(self.request("GET", task_path)[0], 404)
        self.assertEqual(self.request("POST", task_path + "/publish", {}, business)[0], 409)
        status, _, card = self.request("POST", task_path + "/answers", {"answers": [
            "Anonymized tickets in a secure folder", "A prioritization prototype",
            "80% accuracy on a labelled test set", "Support teams need faster triage for support managers",
            "No personal data; Aida will give feedback in weekly video calls",
        ]}, business)
        self.assertEqual(status, 200)
        self.assertEqual(card["status"], "card_ready")
        self.assertIsInstance(card["card"], dict)
        self.assertEqual(self.request("POST", task_path + "/confirm", {}, business)[0], 200)
        self.assertEqual(self.request("POST", task_path + "/publish", {}, business)[0], 200)
        status, _, catalog = self.request("GET", "/api/catalog?limit=1&offset=0", session=business)
        self.assertEqual(status, 200)
        self.assertEqual(catalog["total"], 1)
        self.assertEqual(catalog["items"][0]["id"], task["id"])
        self.assertNotIn("initial_draft", catalog["items"][0])
        self.assertNotIn("answers", catalog["items"][0])
        self.assertNotIn("initial_draft", self.request("GET", f"/api/catalog/{task['id']}", session=business)[2])

        team, _ = self.register("student", "team@example.test")
        team_id = team["data"]["profile"]["id"]
        self.assertEqual(self.request("POST", "/api/tasks", {"business_id": business_id, "initial_draft": "Wrong role."}, team)[0], 403)
        self.assertEqual(self.request("PATCH", task_path + "/card", {"title": "Wrong owner"}, team)[0], 403)
        status, _, proposal = self.request("POST", task_path + "/proposals", {
            "team_id": team_id, "message": "We can help.", "approach": "Prototype, then test."
        }, team)
        self.assertEqual(status, 201)
        self.assertEqual(self.request("GET", task_path + "/proposals", session=team)[0], 403)
        self.assertEqual(self.request("GET", task_path + "/proposals", session=business)[2][0]["team"]["name"], "HTTP team")
        decision_path = f"/api/proposals/{proposal['id']}/decision"
        self.assertEqual(self.request("PATCH", decision_path, {"decision": "accepted"}, team)[0], 403)
        status, _, accepted = self.request("PATCH", decision_path, {"decision": "accepted"}, business)
        self.assertEqual(status, 200)
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(self.request("GET", f"/api/teams/{team_id}/proposals", session=team)[2][0]["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
