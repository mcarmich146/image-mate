"""Background polling for L1D-SR dependencies of durable mosaic jobs."""

from __future__ import annotations

import logging
import threading
from typing import Callable


logger = logging.getLogger("image_mate.mosaic_products")


class MosaicProductPoller:
    """Periodically asks the application service to refresh waiting jobs."""

    def __init__(self, check_callback: Callable[[], None], interval_seconds: int = 300):
        self.check_callback = check_callback
        self.interval_seconds = max(15, int(interval_seconds or 300))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="image-mate-mosaic-products", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        # Waiting can last hours. The first automatic check occurs after the
        # interval; operators can request an immediate check through the API.
        while not self._stop.wait(self.interval_seconds):
            try:
                self.check_callback()
            except Exception as exc:  # pragma: no cover - defensive thread boundary
                logger.warning("mosaic product poll failed: %s", exc)
