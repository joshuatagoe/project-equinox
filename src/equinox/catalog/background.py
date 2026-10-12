"""Keeping the catalog fresh while the web app runs (feat-14, D90).

The server refreshes the catalog when it has none or it is 6 hours old, then every 6 hours (D98),
and when someone presses Refresh. A refresh reads only the venues' public listings and keeps the
model's decisions where both markets' rules are unchanged (D91), so the server never calls the
model. A refresh that fails keeps the previous catalog and says why. Snapshot data is never
refreshed: a snapshot doesn't change.
"""

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from equinox.catalog import CatalogError, load_latest, refresh
from equinox.sources import Settings

EVERY = timedelta(hours=6)  # the user's choice (D98); Refresh is louder as prices age
CHECK = 60.0  # seconds between looks at the clock


@dataclass(frozen=True)
class Status:
    running: bool = False
    problem: str = ""  # why the last refresh failed; "" when it didn't


class Refresher:
    def __init__(
        self,
        settings: Settings,
        *,
        every: timedelta = EVERY,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        run: Callable[[Settings], object] = refresh,
    ) -> None:
        self.settings, self.every, self._clock, self._run = settings, every, clock, run
        self._status = Status()
        self._lock = threading.Lock()
        self._asked = threading.Event()

    def status(self) -> Status:
        return self._status

    def due(self) -> bool:
        """Live data with no catalog, an unreadable one, or one at least `every` old."""
        if self.settings.source != "live":
            return False
        try:
            found = load_latest(self.settings.cache_dir)
        except CatalogError:
            return True
        return found is None or self._clock() - found.summary.refreshed_at >= self.every

    def run_once(self) -> None:
        """Refresh now, unless a refresh is already running or the data is a snapshot, which
        would replace a live catalog in the same folder with the snapshot's sample."""
        if self.settings.source != "live":
            return
        with self._lock:
            if self._status.running:
                return
            self._status = Status(running=True, problem=self._status.problem)
        try:
            self._run(self.settings)
            self._status = Status()
        except CatalogError as error:
            self._status = Status(problem=str(error))
        except Exception as error:  # the loop must outlive one bad refresh; the log has the rest
            traceback.print_exc()
            self._status = Status(problem=f"the refresh stopped: {error}")

    def request(self) -> None:
        """Refresh as soon as the background loop wakes, which is at once."""
        self._asked.set()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._loop, name="catalog-refresh", daemon=True)
        thread.start()
        return thread

    def tick(self) -> None:
        """One turn of the loop: refresh if someone asked, or if one is due."""
        asked = self._asked.is_set()
        self._asked.clear()
        if asked or self.due():
            self.run_once()

    def _loop(self) -> None:
        while True:
            self.tick()
            self._asked.wait(CHECK)
