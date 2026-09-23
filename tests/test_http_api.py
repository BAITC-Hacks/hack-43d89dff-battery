"""Exercise real HTTP parsing and dispatch without requiring a local port."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from backend.api import FRONTEND_DIR, MarketplaceHandler
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
        self.handler = type("TestMarketplaceHandler", (MarketplaceHandler,), {"service": self.service})

    def tearDown(self):
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, token=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        headers = [f"{method} {path} HTTP/1.1", "Host: localhost", "Connection: close"]
        if token:
            headers.append(f"X-Owner-Token: {token}")
        if payload is not None:
            headers.extend(["Content-Type: application/json", f"Content-Length: {len(body)}"])
        connection = MemoryConnection("\r\n".join(headers).encode() + b"\r\n\r\n" + body)
        self.handler(connection, ("127.0.0.1", 0), object())
        raw_headers, result = bytes(connection.response).split(b"\r\n\r\n", 1)
        lines = raw_headers.decode().split("\r\n")
        status = int(lines[0].split()[1])
        response_headers = dict(line.split(": ", 1) for line in lines[1:])
        if response_headers.get("Content-Type", "").startswith("application/json"):
            result = json.loads(result)
        return status, response_headers, result

    def test_frontend_assets_share_the_api_origin(self):
        for path, filename, content_type in [
            ("/", "index.html", "text/html"),
            ("/styles.css", "styles.css", "text/css"),
            ("/api.js", "api.js", "text/javascript"),
            ("/app.js", "app.js", "text/javascript"),
        ]:
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(content_type))
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(body, (FRONTEND_DIR / filename).read_bytes())
        self.assertEqual(self.request("GET", "/health")[2], {"status": "ok"})

    def test_static_routes_cannot_expose_repository_files(self):
        for path in ["/.env", "/agents.md", "/backend/api.py", "/../.env", "/%2e%2e/.env", "/frontend/index.html"]:
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(body["error"]["code"], "route_not_found")

    def test_complete_workflow_and_authorization_through_http(self):
        status, _, business = self.request("POST", "/api/businesses", {"name": "HTTP business"})
        self.assertEqual(status, 201)
        business_token = business["owner_token"]
        status, _, task = self.request("POST", "/api/tasks", {
            "business_id": business["id"], "initial_draft": "Improve how we prioritize support tickets."
        }, business_token)
        self.assertEqual(status, 201)
        self.assertGreaterEqual(len(task["clarifying_questions"]), 3)
        task_path = f"/api/tasks/{task['id']}"
        self.assertEqual(self.request("GET", task_path)[0], 404)
        self.assertEqual(self.request("POST", task_path + "/publish", {}, business_token)[0], 409)
        self.assertEqual(self.request("POST", task_path + "/answers", {"answers": ["a", "b", "c"]}, "invalid")[0], 403)

        status, _, card = self.request("POST", task_path + "/answers", {"answers": [
            "Anonymized tickets in a secure folder", "A prioritization prototype",
            "80% accuracy on a labelled test set",
            "Support teams need faster triage for support managers",
            "No personal data; Aida will give feedback in weekly video calls",
        ]}, business_token)
        self.assertEqual(status, 200)
        self.assertEqual(card["status"], "card_ready")
        self.assertIsInstance(card["card"], dict)
        self.assertEqual(self.request("POST", task_path + "/confirm", {}, business_token)[0], 200)
        self.assertEqual(self.request("POST", task_path + "/publish", {}, business_token)[0], 200)
        status, _, catalog = self.request("GET", "/api/catalog?limit=1&offset=0")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["total"], 1)
        self.assertEqual(catalog["items"][0]["id"], task["id"])
        self.assertNotIn("initial_draft", catalog["items"][0])
        self.assertNotIn("answers", catalog["items"][0])

        _, _, team = self.request("POST", "/api/teams", {"name": "HTTP team", "contact_email": "team@example.test"})
        team_token = team["owner_token"]
        status, _, proposal = self.request("POST", task_path + "/proposals", {
            "team_id": team["id"], "message": "We can help.", "approach": "Prototype, then test."
        }, team_token)
        self.assertEqual(status, 201)
        self.assertEqual(self.request("GET", task_path + "/proposals", token=team_token)[0], 403)
        self.assertEqual(self.request("GET", task_path + "/proposals", token=business_token)[2][0]["team"]["name"], team["name"])
        decision_path = f"/api/proposals/{proposal['id']}/decision"
        self.assertEqual(self.request("PATCH", decision_path, {"decision": "accepted"}, team_token)[0], 403)
        status, _, accepted = self.request("PATCH", decision_path, {"decision": "accepted"}, business_token)
        self.assertEqual(status, 200)
        self.assertEqual(accepted["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
