"""The model behind the term reader: the API key, the Messages API call, and a cache (D57, D58).

The key comes from `ANTHROPIC_API_KEY` or from `.env` at the repository root, which git ignores;
it is never printed. Every request is cached by its content, so reading the same markets with
the same prompt and model again costs nothing, and only changed text is read again.
"""

import hashlib
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

DOTENV = Path(__file__).resolve().parents[3] / ".env"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
KEY_NAME = "ANTHROPIC_API_KEY"

Ask = Callable[[dict[str, Any]], dict[str, Any]]
"""request -> response: the live API, a cache in front of it, or a recorded or fake model."""


class ReaderError(Exception):
    """The model couldn't be asked: no key, or the API kept failing."""


def load_key(env: Mapping[str, str]) -> str | None:
    """The API key from the environment, or else from `.env`; None when neither has one."""
    if env.get(KEY_NAME):
        return env[KEY_NAME]
    try:
        lines = DOTENV.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, equals, value = line.partition("=")
        if equals and name.strip() == KEY_NAME:
            return value.strip().strip("'\"") or None
    return None


class Claude:
    """The Messages API. A 429, a 5xx, an overload or a timeout is retried with a growing pause."""

    def __init__(self, key: str, timeout: float = 120.0, retries: int = 4, pause: float = 5.0):
        self.key, self.timeout, self.retries, self.pause = key, timeout, retries, pause

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            try:
                return self._post(body)
            except urllib.error.HTTPError as error:
                if error.code != 429 and error.code < 500 or attempt == self.retries:
                    detail = error.read().decode("utf-8", "replace")[:300]
                    raise ReaderError(f"the model API answered {error.code}: {detail}") from error
            except OSError as error:  # timeouts, dropped connections
                if attempt == self.retries:
                    raise ReaderError(f"the model API couldn't be reached: {error}") from error
            time.sleep(self.pause * (attempt + 1))
        raise ReaderError("the model API couldn't be reached")

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self.key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())


class Cached:
    """A request that was answered before is answered from disk. Safe across threads."""

    def __init__(self, ask: Ask, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.ask, self.sent, self.reused = ask, 0, 0
        self.input_tokens = self.output_tokens = 0  # spent on requests sent, not on reused ones
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS answers (request TEXT PRIMARY KEY, body TEXT)")

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
        with self._lock:
            found = self._db.execute("SELECT body FROM answers WHERE request = ?", (key,))
            row = found.fetchone()
        if row:
            self.reused += 1
            return json.loads(row[0])
        answer = self.ask(body)
        with self._lock:
            row = (key, json.dumps(answer))
            self._db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?)", row)
            self._db.commit()
            self.sent += 1
            used = answer.get("usage") or {}
            self.input_tokens += int(used.get("input_tokens") or 0)
            self.output_tokens += int(used.get("output_tokens") or 0)
        return answer
