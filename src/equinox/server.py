"""The local web server: the UI's pages (feat-07) and the /health check."""

from __future__ import annotations

import argparse
import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from equinox import health
from equinox.catalog.background import Refresher
from equinox.sources import Settings
from equinox.web import App

_default: App | None = None
_default_lock = threading.Lock()


def default_app() -> App:
    """One App per process, with settings from the environment (architecture section 11)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = App(Settings.from_env(os.environ))
        return _default


class Handler(BaseHTTPRequestHandler):
    app: App | None = None

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = self.path.partition("?")
        if path == "/health":
            body = json.dumps(health()).encode()
            self._send(200, "application/json; charset=utf-8", body)
            return
        try:
            page = (type(self).app or default_app()).respond(path, query)
        except Exception:  # show a plain error page; the details go to the console only
            traceback.print_exc()
            self._send(
                500, "text/plain; charset=utf-8", b"Something went wrong. See the server log.\n"
            )
            return
        if page is None:
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        """Only Refresh posts: ask for a refresh, then go back to the page."""
        app = type(self).app or default_app()
        if self.path.partition("?")[0] != "/refresh" or not app.refresh():
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        self.send_response(303)
        self.send_header("Location", self._back())
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _back(self) -> str:
        """The page Refresh was pressed on, when it is one of this app's; else Markets."""
        came = urlsplit(self.headers.get("Referer", ""))
        if came.netloc != self.headers.get("Host") or not came.path.startswith("/"):
            return "/"
        return came.path + (f"?{came.query}" if came.query else "")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} {fmt % args}")


def make_handler(app: App) -> type[Handler]:
    """A handler class bound to one App, for tests and embedding."""
    return type("EquinoxHandler", (Handler,), {"app": app})


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Project Equinox web UI")
    parser.add_argument("--host", default="127.0.0.1", help="default: this computer only")
    parser.add_argument("--port", type=int, default=8741)
    args = parser.parse_args()
    settings = Settings.from_env(os.environ)
    refresher = Refresher(settings) if settings.source == "live" else None
    app = App(settings, refresher=refresher)
    if refresher is not None:  # the catalog keeps itself fresh (D90)
        refresher.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"Project Equinox is running. Open http://{args.host}:{args.port} in a browser.")
    server.serve_forever()


if __name__ == "__main__":
    main()
