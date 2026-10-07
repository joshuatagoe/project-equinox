import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from equinox import health
from equinox.server import Handler


def test_health_names_both_hosts():
    payload = health()
    assert payload["name"] == "project-equinox"
    assert payload["status"] == "ok"
    assert payload["hosts"] == ["github", "gitlab"]


def test_status_page_and_health_route():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as response:
            payload = json.load(response)
        assert payload["status"] == "ok"
        assert "github" in payload["hosts"]

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            page = response.read().decode()
        assert "Project Equinox" in page
        assert response.status == 200

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/missing")
        except urllib.error.HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("expected 404")
    finally:
        server.shutdown()
