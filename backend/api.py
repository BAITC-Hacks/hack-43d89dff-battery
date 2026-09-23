"""Dependency-free JSON HTTP API for the marketplace MVP.

Run with: ``python3 -m backend.api``
"""

from __future__ import annotations

import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .database import Database
from .service import MarketplaceService, ServiceError


MAX_BODY_BYTES = 1_000_000
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


class MarketplaceHandler(BaseHTTPRequestHandler):
    """Routes the small REST surface to ``MarketplaceService``."""

    service: MarketplaceService
    server_version = "TaskMarketplace/1.0"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(HTTPStatus.NO_CONTENT, None)

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
        try:
            result, status = self._route(method, path, query)
            self._send(status, result)
        except ServiceError as error:
            self._send(error.status, {"error": {"code": error.code, "message": error.message}})
        except json.JSONDecodeError:
            self._send(400, {"error": {"code": "invalid_json", "message": "Request body must be valid JSON."}})
        except ValueError as error:
            self._send(422, {"error": {"code": "validation_error", "message": str(error)}})
        except Exception:
            # Deliberately do not leak internals or configuration through the API.
            self.log_error("Unhandled API error")
            self._send(500, {"error": {"code": "internal_error", "message": "Unexpected server error."}})

    def _route(self, method: str, path: str, query: dict[str, list[str]]) -> tuple[Any, int]:
        token = self.headers.get("X-Owner-Token")
        if method == "GET" and path == "/health":
            return {"status": "ok"}, 200
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
        if method == "POST" and path == "/api/businesses":
            return self.service.create_business(self._body()), 201
        if method == "POST" and path == "/api/teams":
            return self.service.create_team(self._body()), 201
        if method == "POST" and path == "/api/tasks":
            return self.service.create_task(self._body(), token), 201
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
                return self.service.get_task(match.group(1), token), 200
        if match := TASK_ANSWERS_ROUTE.match(path):
            if method == "POST":
                return self.service.submit_answers(match.group(1), self._body(), token), 200
        if match := TASK_CARD_ROUTE.match(path):
            if method == "PATCH":
                return self.service.update_card(match.group(1), self._body(), token), 200
        if match := TASK_CONFIRM_ROUTE.match(path):
            if method == "POST":
                return self.service.confirm_task(match.group(1), token), 200
        if match := TASK_PUBLISH_ROUTE.match(path):
            if method == "POST":
                return self.service.publish_task(match.group(1), token), 200
        if match := TASK_PROPOSALS_ROUTE.match(path):
            if method == "POST":
                return self.service.create_proposal(match.group(1), self._body(), token), 201
            if method == "GET":
                return self.service.list_task_proposals(match.group(1), token), 200
        if match := BUSINESS_TASKS_ROUTE.match(path):
            if method == "GET":
                return self.service.list_business_tasks(match.group(1), token), 200
        if match := TEAM_PROPOSALS_ROUTE.match(path):
            if method == "GET":
                return self.service.list_team_proposals(match.group(1), token), 200
        if match := CATALOG_TASK_ROUTE.match(path):
            if method == "GET":
                return self.service.get_task(match.group(1)), 200
        if match := PROPOSAL_DECISION_ROUTE.match(path):
            if method == "PATCH":
                body = self._body()
                return self.service.decide_proposal(match.group(1), body.get("decision"), token), 200
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
        self.send_header("Access-Control-Allow-Origin", os.getenv("CORS_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Owner-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
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
    handler = type("ConfiguredMarketplaceHandler", (MarketplaceHandler,), {"service": service})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    host = os.getenv("MARKETPLACE_HOST", "127.0.0.1")
    port = int(os.getenv("MARKETPLACE_PORT", "8000"))
    server = create_server(host, port)
    print(f"Marketplace API listening on http://{host}:{port}")
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


if __name__ == "__main__":
    main()
