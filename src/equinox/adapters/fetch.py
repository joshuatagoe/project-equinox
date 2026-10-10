"""The two fetchers: live HTTP, and a saved snapshot. An adapter can't tell which it has."""

import json
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from equinox.adapters.base import FetchError

DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "snapshot-2026-10-10"
USER_AGENT = "project-equinox/0.1 (prototype; read-only)"


class HttpFetcher:
    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def __call__(self, url: str) -> Any:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
            return json.loads(body, parse_float=Decimal)
        except (OSError, ValueError) as error:  # URLError, HTTPError, timeouts, bad JSON
            raise FetchError(f"{url}: {error}") from error


def _url_key(url: str) -> tuple:
    """The URL with its query parameters in a fixed order."""
    parts = urlsplit(url)
    query = tuple(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return parts.scheme, parts.netloc, parts.path, query


class FixtureFetcher:
    """Serves a snapshot directory: raw responses plus index.json {captured_at, files}."""

    def __init__(self, snapshot_dir: Path) -> None:
        self.snapshot_dir = Path(snapshot_dir)
        try:
            index = json.loads((self.snapshot_dir / "index.json").read_text(encoding="utf-8"))
            files = index["files"]
            captured_at = datetime.fromisoformat(index["captured_at"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise FetchError(f"{self.snapshot_dir}: no usable index.json ({error})") from error
        if captured_at.tzinfo is None:
            raise FetchError(f"{self.snapshot_dir}: captured_at has no time zone")
        self.captured_at = captured_at.astimezone(UTC)  # the snapshot's clock (D37)
        self._files = {_url_key(url): name for name, url in files.items()}

    def __call__(self, url: str) -> Any:
        name = self._files.get(_url_key(url))
        if name is None:
            raise FetchError(f"{url}: not in the snapshot {self.snapshot_dir.name}")
        try:
            body = (self.snapshot_dir / name).read_text(encoding="utf-8")
            return json.loads(body, parse_float=Decimal)
        except (OSError, ValueError) as error:
            raise FetchError(f"{url}: fixture {name} unreadable ({error})") from error
