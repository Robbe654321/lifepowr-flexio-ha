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

#: Options key: learn the roof and publish a solar forecast.
CONF_SOLAR_FORECAST: Final = "solar_forecast"

#: Options key: read the production history from another entity instead. Handy
#: when an older inverter integration holds years of history the FlexiObox
#: cannot know about.
CONF_SOLAR_SOURCE: Final = "solar_source"

#: Options key: how far back to read that history.
CONF_SOLAR_HISTORY_DAYS: Final = "solar_history_days"

DEFAULT_SOLAR_FORECAST: Final = False

#: A year covers every sun angle the site will ever see, which is what pins
#: the tilt down. More is welcome and costs only a slower nightly fit.
DEFAULT_SOLAR_HISTORY_DAYS: Final = 365
MIN_SOLAR_HISTORY_DAYS: Final = 30
MAX_SOLAR_HISTORY_DAYS: Final = 730

#: How often the forecast is refreshed against the weather service.
SOLAR_FORECAST_INTERVAL: Final = timedelta(minutes=30)

#: The roof is not going to move, so the fit runs nightly at the quietest
#: hour rather than on any kind of loop.
SOLAR_LEARN_HOUR: Final = 3

#: Re-learn if the stored model is older than this, so a fresh install and a
#: long outage both recover without the user asking.
SOLAR_MODEL_MAX_AGE: Final = timedelta(days=7)

#: Storage
SOLAR_STORE_VERSION: Final = 1
SOLAR_STORE_KEY: Final = f"{DOMAIN}.solar_model"

SERVICE_LEARN_SOLAR_MODEL: Final = "learn_solar_model"
