"""Local status server for Project Equinox."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from equinox import health

PAGE = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            body = json.dumps(health()).encode()
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode())
            return
        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Project Equinox status page")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8741)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Project Equinox listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
