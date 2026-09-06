"""Irradiance from Open-Meteo, for both learning and forecasting.

The FlexiObox measures what the panels produced. To turn that into geometry,
and geometry back into a forecast, something has to say what the sky was doing
-- and the split between hard direct sunlight and the soft glow off the rest
of the sky is what a tilted plane responds to differently from a flat one.

:mod:`solar` can model a *cloudless* sky offline, which is enough to spot the
clear intervals a fit needs. It cannot say how cloudy next Tuesday will be, and
its beam/diffuse split carries a bias that the learned tilt then has to absorb.
Open-Meteo publishes both the measured past and the forecast future, free and
without an API key, which removes the guesswork from both ends.

The one detail worth stating plainly: **Open-Meteo timestamps the end of each
hour**. The value at 12:00 is the average over 11:00-12:00. That was confirmed
against the service's own ``direct_radiation`` and ``direct_normal_irradiance``
pair, whose ratio is the cosine of the zenith angle it used -- and that cosine
matches 11:30, the middle of the preceding hour. Getting this backwards shifts
every sky by an hour, which a fit happily absorbs by rotating the roof 15
degrees westwards.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from aiohttp import ClientError, ClientSession

from .const import LOGGER, REQUEST_TIMEOUT
from .solar import Irradiance

FORECAST_URL: Final = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL: Final = "https://archive-api.open-meteo.com/v1/archive"

#: Global horizontal, direct normal, diffuse horizontal, and the air
#: temperature that decides how much the panels lose to heat.
_HOURLY: Final = (
    "shortwave_radiation",
    "direct_normal_irradiance",
    "diffuse_radiation",
    "temperature_2m",
)

#: The reanalysis behind the archive endpoint trails real time by a few days.
ARCHIVE_LAG: Final = timedelta(days=6)

#: Most days of history one request may ask for. Comfortably inside the free
#: tier, and a fit gains little from a longer window than a couple of years.
MAX_HISTORY_DAYS: Final = 730


class OpenMeteoError(Exception):
    """Raised when the weather service cannot be reached or understood."""


@dataclass(frozen=True, slots=True)
class SkyHour:
    """What the sky delivered, or will deliver, over one hour."""

    start: datetime
    end: datetime
    sky: Irradiance
    temperature: float | None


class OpenMeteoClient:
    """Read hourly irradiance for one location."""

    def __init__(
        self,
        session: ClientSession,
        latitude: float,
        longitude: float,
    ) -> None:
        """Initialise the client for a site."""
        self._session = session
        self._latitude = latitude
        self._longitude = longitude

    async def async_forecast(self, days: int = 3) -> list[SkyHour]:
        """Return the coming days' sky, hour by hour."""
        return await self._async_read(
            FORECAST_URL,
            {"forecast_days": days, "past_days": 1},
        )

    async def async_history(self, start: date, end: date) -> list[SkyHour]:
        """Return the measured sky between two dates, inclusive."""
        if start > end:
            return []
        return await self._async_read(
            ARCHIVE_URL,
            {"start_date": start.isoformat(), "end_date": end.isoformat()},
        )

    async def _async_read(
        self, url: str, extra: dict[str, Any]
    ) -> list[SkyHour]:
        """Fetch one endpoint and map it onto hours."""
        params = {
            "latitude": self._latitude,
            "longitude": self._longitude,
            "hourly": ",".join(_HOURLY),
            "timezone": "UTC",
            "timeformat": "unixtime",
            **extra,
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT * 6):
                response = await self._session.get(url, params=params)
                response.raise_for_status()
                payload = await response.json()
        except TimeoutError as err:
            raise OpenMeteoError(f"{url} timed out") from err
        except ClientError as err:
            raise OpenMeteoError(f"{url} could not be reached: {err}") from err
        except ValueError as err:
            raise OpenMeteoError(f"{url} returned unreadable data") from err

        if payload.get("error"):
            raise OpenMeteoError(str(payload.get("reason", "unknown error")))
        return _parse(payload)


def _parse(payload: Any) -> list[SkyHour]:
    """Map an Open-Meteo document onto hours, discarding unusable rows."""
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise OpenMeteoError("no hourly data in the response")

    times = hourly["time"]
    ghi = hourly.get("shortwave_radiation") or []
    dni = hourly.get("direct_normal_irradiance") or []
    dhi = hourly.get("diffuse_radiation") or []
    temperature = hourly.get("temperature_2m") or []

    hours: list[SkyHour] = []
    for index, stamp in enumerate(times):
        values = [
            _number(series, index) for series in (ghi, dni, dhi)
        ]
        if any(value is None for value in values):
            # A missing component would silently read as a dark sky.
            continue
        end = datetime.fromtimestamp(stamp, tz=UTC)
        hours.append(
            SkyHour(
                start=end - timedelta(hours=1),
                end=end,
                sky=Irradiance(
                    ghi=max(values[0] or 0.0, 0.0),
                    dni=max(values[1] or 0.0, 0.0),
                    dhi=max(values[2] or 0.0, 0.0),
                ),
                temperature=_number(temperature, index),
            )
        )
    if not hours:
        raise OpenMeteoError("the response held no usable hours")
    LOGGER.debug("Open-Meteo returned %d hours", len(hours))
    return hours


def _number(series: list[Any], index: int) -> float | None:
    """Return one value of a series as a float, or None when absent."""
    if index >= len(series):
        return None
    value = series[index]
    return float(value) if isinstance(value, (int, float)) else None
