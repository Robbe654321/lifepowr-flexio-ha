"""Constants for the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "lifepowr"

LOGGER: Final = logging.getLogger(__package__)

DEFAULT_HOST: Final = "myio.local"
DEFAULT_NAME: Final = "FlexiO"

#: Default poll interval. The box is local and answers in milliseconds, so
#: this is a comfort default rather than a limit; it is configurable per entry.
DEFAULT_SCAN_INTERVAL: Final = 10

#: Faster than this hammers the box for no benefit — its values are filtered
#: and the vendor's own app refreshes every few seconds.
MIN_SCAN_INTERVAL: Final = 2
MAX_SCAN_INTERVAL: Final = 300

SCAN_INTERVAL: Final = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

#: Total time budget for a single request to the box.
REQUEST_TIMEOUT: Final = 10

MANUFACTURER: Final = "LIFEPOWR"
MODEL: Final = "FlexiO"
