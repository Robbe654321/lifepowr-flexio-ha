"""Tests for the Open-Meteo irradiance client."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from aiohttp import ClientError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.lifepowr.openmeteo import (
    ARCHIVE_URL,
    FORECAST_URL,
    OpenMeteoClient,
    OpenMeteoError,
    _parse,
)

#: 2024-06-21 11:00 and 12:00 UTC.
NOON = 1718967600
PAYLOAD = {
    "hourly": {
        "time": [NOON, NOON + 3600],
        "shortwave_radiation": [800.0, 850.0],
        "direct_normal_irradiance": [700.0, 720.0],
        "diffuse_radiation": [180.0, 190.0],
        "temperature_2m": [21.0, 22.5],
    }
}


def test_hours_are_labelled_at_their_end() -> None:
    """Open-Meteo timestamps the end of the averaging interval.

    Confirmed against the service's own direct_radiation and
    direct_normal_irradiance pair, whose ratio is the cosine of the zenith it
    used: that cosine matches the middle of the *preceding* hour. Reading it
    the other way round shifts every sky an hour later, which a fit absorbs by
    rotating the roof fifteen degrees to the west.
    """
    hours = _parse(PAYLOAD)
    assert hours[0].end == datetime(2024, 6, 21, 11, 0, tzinfo=UTC)
    assert hours[0].start == datetime(2024, 6, 21, 10, 0, tzinfo=UTC)
    assert hours[0].end - hours[0].start == timedelta(hours=1)


def test_parses_the_sky_and_the_temperature() -> None:
    """Every component the transposition needs comes through."""
    first = _parse(PAYLOAD)[0]
    assert first.sky.ghi == 800.0
    assert first.sky.dni == 700.0
    assert first.sky.dhi == 180.0
    assert first.temperature == 21.0


def test_hours_missing_a_component_are_dropped() -> None:
    """A missing component would otherwise read as a dark sky."""
    payload = {
        "hourly": {
            "time": [NOON, NOON + 3600],
            "shortwave_radiation": [800.0, None],
            "direct_normal_irradiance": [700.0, 720.0],
            "diffuse_radiation": [180.0, 190.0],
            "temperature_2m": [21.0, 22.5],
        }
    }
    hours = _parse(payload)
    assert len(hours) == 1
    assert hours[0].sky.ghi == 800.0


def test_a_missing_temperature_is_allowed() -> None:
    """The fit works without it; it just cannot correct for heat."""
    payload = {"hourly": dict(PAYLOAD["hourly"], temperature_2m=[])}
    assert _parse(payload)[0].temperature is None


@pytest.mark.parametrize(
    "payload", [{}, {"hourly": {}}, {"hourly": {"time": []}}, {"hourly": None}]
)
def test_unusable_responses_are_rejected(payload) -> None:
    """Nothing usable has to raise rather than quietly return no sky."""
    with pytest.raises(OpenMeteoError):
        _parse(payload)


async def test_forecast_asks_the_forecast_endpoint(hass, aioclient_mock) -> None:
    """And gets hours back."""
    aioclient_mock.get(FORECAST_URL, json=PAYLOAD)
    client = OpenMeteoClient(_session(hass), 51.05, 3.72)
    hours = await client.async_forecast()
    assert len(hours) == 2
    assert aioclient_mock.mock_calls[0][1].query["latitude"] == "51.05"


async def test_history_asks_the_archive_endpoint(hass, aioclient_mock) -> None:
    """The archive takes a date range."""
    aioclient_mock.get(ARCHIVE_URL, json=PAYLOAD)
    client = OpenMeteoClient(_session(hass), 51.05, 3.72)
    hours = await client.async_history(date(2024, 6, 1), date(2024, 6, 21))
    assert len(hours) == 2
    query = aioclient_mock.mock_calls[0][1].query
    assert query["start_date"] == "2024-06-01"
    assert query["end_date"] == "2024-06-21"


async def test_a_backwards_range_asks_nothing(hass, aioclient_mock) -> None:
    """Which happens on a fresh install with no history behind it."""
    client = OpenMeteoClient(_session(hass), 51.05, 3.72)
    assert await client.async_history(date(2024, 6, 21), date(2024, 6, 1)) == []
    assert not aioclient_mock.mock_calls


async def test_a_service_error_is_reported(hass, aioclient_mock) -> None:
    """Open-Meteo answers 200 with an error body when it refuses."""
    aioclient_mock.get(
        FORECAST_URL, json={"error": True, "reason": "Daily API request limit exceeded"}
    )
    client = OpenMeteoClient(_session(hass), 51.05, 3.72)
    with pytest.raises(OpenMeteoError, match="limit exceeded"):
        await client.async_forecast()


async def test_an_unreachable_service_is_reported(hass, aioclient_mock) -> None:
    """A network failure must not escape as an aiohttp error."""
    aioclient_mock.get(FORECAST_URL, exc=ClientError("no route"))
    client = OpenMeteoClient(_session(hass), 51.05, 3.72)
    with pytest.raises(OpenMeteoError):
        await client.async_forecast()


def _session(hass):
    """Return the shared aiohttp session."""
    return async_get_clientsession(hass)
