"""A tiny, fictional inventory API matching examples/sample-api.yaml.

Standard library only. Binds to 127.0.0.1 and serves synthetic data.

    python examples/mock_api.py --port 8000
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

HOST = "127.0.0.1"

ITEMS = [
    {"id": "item-001", "name": "Example widget", "category": "tools", "price": 4.99},
    {"id": "item-002", "name": "Sample gadget", "category": "tools", "price": 12.50},
    {"id": "item-003", "name": "Demo gizmo", "category": "toys", "price": 7.25},
]


class MockApiHandler(BaseHTTPRequestHandler):
    server_version = "QaPlatformMockAPI/0.1"

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        segments = [unquote(part) for part in url.path.strip("/").split("/") if part]

        if segments == ["health"]:
            self._send_json(200, {"status": "ok"})
        elif segments == ["items"]:
            self._list_items(query)
        elif len(segments) == 2 and segments[0] == "items":
            item = next((item for item in ITEMS if item["id"] == segments[1]), None)
            if item is None:
                self._send_json(404, {"error": f"item {segments[1]!r} not found"})
            else:
                self._send_json(200, item)
        else:
            self._send_json(404, {"error": "not found"})

    def _list_items(self, query: dict[str, list[str]]) -> None:
        items = ITEMS
        if "category" in query:
            items = [item for item in items if item["category"] == query["category"][0]]
        if "limit" in query:
            try:
                limit = int(query["limit"][0])
            except ValueError:
                limit = 0
            if limit < 1:
                self._send_json(400, {"error": "limit must be a positive integer"})
                return
            items = items[:limit]
        self._send_json(200, items)

    def _method_not_allowed(self) -> None:
        self._send_json(405, {"error": "method not allowed"})

    do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed

    def _send_json(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fictional sample API on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")

    server = ThreadingHTTPServer((HOST, args.port), MockApiHandler)
    print(f"Mock API listening on http://{HOST}:{server.server_address[1]} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
