#!/usr/bin/env python3
"""Built-in HTTP server serving static files and API endpoints."""

import json
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# Import our models
from models.generateQuestions import generate_questions
from models.generateTaskCard import generate_task_card
from models.evaluateTaskCard import evaluate_task_card

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Absolute paths based on this file's location
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


class ServerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Initialize serving from the frontend directory
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_POST(self):
        parsed_url = urlparse(self.path)
        
        # Route: generate questions
        if parsed_url.path == "/api/generate-questions":
            self._handle_json_api(generate_questions)
        # Route: generate task card
        elif parsed_url.path == "/api/generate-task-card":
            self._handle_json_api(generate_task_card)
        # Route: evaluate task card
        elif parsed_url.path == "/api/evaluate-task":
            self._handle_json_api(evaluate_task_card)
        else:
            self.send_error(404, "Endpoint Not Found")

    def _handle_json_api(self, handler_function):
        """Helper to parse JSON input, call handler, and return JSON."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Empty request body")
            return

        try:
            body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON payload")
            return

        try:
            result = handler_function(payload)
            self._send_json_response(200, result)
        except Exception as e:
            logger.exception("Error handling API request")
            self._send_json_response(500, {"error": str(e)})

    def _send_json_response(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    # Support CORS for local development
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run(port=8000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, ServerHandler)
    logger.info(f"Starting server on port {port} (serving {FRONTEND_DIR})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        logger.info("Server stopped.")


if __name__ == "__main__":
    FRONTEND_DIR.mkdir(exist_ok=True)
    run()
