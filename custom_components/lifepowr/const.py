"""Constants for the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "lifepowr"

LOGGER: Final = logging.getLogger(__package__)

DEFAULT_HOST: Final = "myio.local"
DEFAULT_NAME: Final = "FlexiO"

#: The FlexiObox exposes live measurements only; polling faster than this adds
#: load without adding resolution to the underlying filtered values.
SCAN_INTERVAL: Final = timedelta(seconds=15)

#: Total time budget for a single request to the box.
REQUEST_TIMEOUT: Final = 10

MANUFACTURER: Final = "LIFEPOWR"
MODEL: Final = "FlexiO"
