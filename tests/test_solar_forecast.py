"""Tests for the solar forecast as Home Assistant sees it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lifepowr.const import (
    CONF_SOLAR_FORECAST,
    CONF_SOLAR_HISTORY_DAYS,
    DOMAIN,
    SERVICE_LEARN_SOLAR_MODEL,
)
from custom_components.lifepowr.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.lifepowr.openmeteo import ARCHIVE_URL, FORECAST_URL
from custom_components.lifepowr.solar import Irradiance
from custom_components.lifepowr.solar_forecast import SolarForecast

from .conftest import ENTRY_ID, HOST
from .test_learning import LAT, LON, synthesise

MODEL_SENSOR = "sensor.flexio_learned_solar_capacity"
TODAY_SENSOR = "sensor.flexio_solar_forecast_today"


def _forecast_payload(start: datetime, hours: int = 48) -> dict:
    """Return an Open-Meteo style forecast of steady midday sun."""
    times, ghi, dni, dhi, temperature = [], [], [], [], []
    for index in range(hours):
        end = start + timedelta(hours=index + 1)
        daylight = 8 <= end.hour <= 18
        times.append(int(end.timestamp()))
        ghi.append(600.0 if daylight else 0.0)
        dni.append(700.0 if daylight else 0.0)
        dhi.append(150.0 if daylight else 0.0)
        temperature.append(18.0)
    return {
        "hourly": {
            "time": times,
            "shortwave_radiation": ghi,
            "direct_normal_irradiance": dni,
            "diffuse_radiation": dhi,
            "temperature_2m": temperature,
        }
    }


class _Recorder:
    """Stands in for the recorder instance, running its jobs inline."""

    async def async_add_executor_job(self, target, *args):
        return target(*args)


@pytest.fixture
def with_recorder(hass: HomeAssistant) -> None:
    """Pretend the recorder is set up, which is where the history lives."""
    hass.config.components.add("recorder")


#: Mid-morning on the longest day, so "today" still has a full sky ahead of
#: it. Without pinning the clock these tests pass or fail by the hour they run.
FROZEN_NOW = datetime(2026, 6, 21, 8, 0, tzinfo=UTC)


@pytest.fixture
async def solar_entry(hass: HomeAssistant, freezer) -> MockConfigEntry:
    """Return a config entry with the solar forecast switched on.

    The clock matters as much as the coordinates here: "today" is a local
    calendar day, so a Belgian roof on a Californian clock would total up the
    wrong twenty-four hours.
    """
    freezer.move_to(FROZEN_NOW)
    hass.config.latitude = LAT
    hass.config.longitude = LON
    hass.config.elevation = 10
    await hass.config.async_set_time_zone("Europe/Brussels")
    return MockConfigEntry(
        domain=DOMAIN,
        title="FlexiO",
        data={"host": HOST},
        options={
            CONF_SCAN_INTERVAL: 10,
            CONF_SOLAR_FORECAST: True,
            CONF_SOLAR_HISTORY_DAYS: 365,
        },
        entry_id=ENTRY_ID,
    )


@pytest.fixture
def mock_history():
    """Serve a synthetic year of hourly production out of the recorder."""
    samples = synthesise([(30.0, 100.0, 4000.0), (30.0, 260.0, 3000.0)])
    rows = [
        {"start": sample.start.timestamp(), "mean": sample.power}
        for sample in samples
    ]

    def _statistics(hass, start, end, statistic_ids, period, units, types):
        return {next(iter(statistic_ids)): rows}

    with (
        patch(
            "custom_components.lifepowr.solar_forecast.get_instance",
            return_value=_Recorder(),
        ),
        patch(
            "custom_components.lifepowr.solar_forecast.statistics_during_period",
            _statistics,
        ),
    ):
        yield rows


@pytest.fixture
async def init_solar(
    hass, solar_entry, with_recorder, mock_client, mock_history, aioclient_mock
):
    """Set the integration up with the forecast enabled and a roof to learn."""
    aioclient_mock.get(FORECAST_URL, json=_forecast_payload(_hour_floor()))
    # The archive refuses, so the fit falls back on its own cloudless-sky
    # model -- the path that has to work when the service is unreachable.
    aioclient_mock.get(ARCHIVE_URL, status=404)
    solar_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(solar_entry.entry_id)
    # The fit is deliberately a background task, so setup does not block on a
    # second of arithmetic; the tests have to wait for it explicitly.
    await hass.async_block_till_done(wait_background_tasks=True)
    solar = solar_entry.runtime_data.solar
    assert solar is not None
    await solar.async_refresh()
    await hass.async_block_till_done()
    return solar_entry


def _hour_floor() -> datetime:
    """Return the start of the current UTC hour."""
    return dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=1
    )


# --------------------------------------------------------------------------
# The forecast container
# --------------------------------------------------------------------------


def test_energy_clips_partial_hours() -> None:
    """"The rest of today" has to mean exactly that, mid-hour included."""
    start = datetime(2024, 6, 21, 10, 0, tzinfo=UTC)
    forecast = SolarForecast(
        hours=((start, 2000.0), (start + timedelta(hours=1), 4000.0))
    )
    assert forecast.energy(start, start + timedelta(hours=2)) == pytest.approx(6.0)
    assert forecast.energy(
        start + timedelta(minutes=30), start + timedelta(hours=2)
    ) == pytest.approx(5.0)
    assert forecast.energy(
        start - timedelta(days=1), start - timedelta(hours=12)
    ) == 0.0


def test_power_and_peak_read_the_right_hour() -> None:
    """Both answer from the hour containing the moment asked about."""
    start = datetime(2024, 6, 21, 10, 0, tzinfo=UTC)
    forecast = SolarForecast(
        hours=((start, 2000.0), (start + timedelta(hours=1), 4000.0))
    )
    assert forecast.power_at(start + timedelta(minutes=59)) == 2000.0
    assert forecast.power_at(start + timedelta(hours=1)) == 4000.0
    assert forecast.power_at(start + timedelta(days=1)) is None
    peak = forecast.peak(start, start + timedelta(hours=2))
    assert peak == (start + timedelta(hours=1), 4000.0)


def test_an_all_dark_window_has_no_peak() -> None:
    """A December day with nothing in it reports nothing, not zero watts."""
    start = datetime(2024, 12, 21, 2, 0, tzinfo=UTC)
    forecast = SolarForecast(hours=((start, 0.0),))
    assert forecast.peak(start, start + timedelta(hours=1)) is None


def test_an_empty_forecast_is_unavailable() -> None:
    """No model and no sky means the entities say so."""
    assert not SolarForecast().available


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


async def test_learns_a_roof_and_forecasts_with_it(hass, init_solar) -> None:
    """The whole path: recorder history in, roof out, forecast published."""
    solar = init_solar.runtime_data.solar
    assert solar.model is not None
    assert len(solar.model.arrays) == 2
    assert solar.model.peak_power == pytest.approx(7000.0, rel=0.2)

    state = hass.states.get(MODEL_SENSOR)
    assert state is not None
    assert float(state.state) == pytest.approx(solar.model.peak_power, abs=1.0)
    assert len(state.attributes["arrays"]) == 2
    assert state.attributes["held_out_r2"] > 0.85
    assert "orientation" in state.attributes["arrays"][0]

    today = hass.states.get(TODAY_SENSOR)
    assert today is not None
    assert float(today.state) > 0.0


async def test_the_model_is_restored_after_a_restart(
    hass, init_solar, mock_history
) -> None:
    """A year of evidence must not be thrown away by a reboot."""
    learned = init_solar.runtime_data.solar.model
    assert learned is not None

    assert await hass.config_entries.async_reload(init_solar.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    restored = init_solar.runtime_data.solar.model
    assert restored is not None
    assert restored.created == learned.created
    # Storage rounds; the roof has to come back the same to within that.
    assert len(restored.arrays) == len(learned.arrays)
    for saved, original in zip(restored.arrays, learned.arrays, strict=True):
        assert saved.tilt == pytest.approx(original.tilt, abs=0.05)
        assert saved.azimuth == pytest.approx(original.azimuth, abs=0.05)
        assert saved.peak_power == pytest.approx(original.peak_power, abs=0.05)


async def test_a_model_learned_elsewhere_is_discarded(hass, init_solar) -> None:
    """The sun does not stand where a model from another country assumed."""
    solar = init_solar.runtime_data.solar
    hass.config.latitude = 40.0
    solar.model = None
    assert await solar.async_load_model() is None


async def test_the_forecast_survives_a_weather_outage(
    hass, init_solar, aioclient_mock
) -> None:
    """Yesterday's numbers beat a blank dashboard, and say they are stale."""
    solar = init_solar.runtime_data.solar
    before = solar.data.hours
    assert before

    aioclient_mock.clear_requests()
    aioclient_mock.get(FORECAST_URL, status=500)
    aioclient_mock.get(ARCHIVE_URL, status=404)
    await solar.async_refresh()

    assert solar.data.error is not None
    assert solar.data.hours == before


async def test_the_service_relearns_the_roof(hass, init_solar) -> None:
    """Called by hand after adding panels, rather than waiting for the night."""
    solar = init_solar.runtime_data.solar
    first = solar.model
    with patch.object(
        solar, "async_learn", wraps=solar.async_learn
    ) as relearn:
        await hass.services.async_call(
            DOMAIN, SERVICE_LEARN_SOLAR_MODEL, {}, blocking=True
        )
    assert relearn.called
    assert solar.model is not None
    assert solar.model.arrays == first.arrays


async def test_the_service_complains_when_the_forecast_is_off(
    hass, init_integration
) -> None:
    """Rather than silently doing nothing."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_LEARN_SOLAR_MODEL, {}, blocking=True
        )


async def test_no_solar_entities_when_the_option_is_off(
    hass, init_integration
) -> None:
    """The forecast is opt-in, and leaves no trace when it is not asked for."""
    assert init_integration.runtime_data.solar is None
    assert hass.states.get(MODEL_SENSOR) is None
    assert hass.states.get(TODAY_SENSOR) is None


async def test_too_little_history_leaves_the_roof_unlearned(
    hass, solar_entry, with_recorder, mock_client, aioclient_mock
) -> None:
    """A fresh install has nothing to learn from, and must say so quietly."""
    aioclient_mock.get(FORECAST_URL, json=_forecast_payload(_hour_floor()))
    aioclient_mock.get(ARCHIVE_URL, status=404)
    with (
        patch(
            "custom_components.lifepowr.solar_forecast.get_instance",
            return_value=_Recorder(),
        ),
        patch(
            "custom_components.lifepowr.solar_forecast.statistics_during_period",
            lambda *args: {},
        ),
    ):
        solar_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(solar_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    solar = solar_entry.runtime_data.solar
    assert solar is not None
    assert solar.model is None
    assert hass.states.get(MODEL_SENSOR).state == "unavailable"


async def test_no_forecast_without_the_recorder(
    hass, solar_entry, mock_client
) -> None:
    """The statistics are where the history lives; without them there is none."""
    assert "recorder" not in hass.config.components
    solar_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(solar_entry.entry_id)
    await hass.async_block_till_done()
    assert solar_entry.runtime_data.solar is None


async def test_the_model_powers_a_dark_hour_at_zero(hass, init_solar) -> None:
    """Night is night, whatever the weather service says about temperature."""
    solar = init_solar.runtime_data.solar
    midnight = datetime(2024, 12, 21, 1, 0, tzinfo=UTC)
    assert solar.model.power(
        midnight, midnight + timedelta(hours=1), Irradiance(0.0, 0.0, 0.0)
    ) == 0.0


async def test_the_action_exists_without_any_box(hass) -> None:
    """Registered in async_setup, so it can explain itself rather than vanish.

    An action that disappears when no FlexiObox is loaded gives an automation
    referencing it nothing to report but "unknown service".
    """
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, SERVICE_LEARN_SOLAR_MODEL)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_LEARN_SOLAR_MODEL, {}, blocking=True
        )


async def test_diagnostics_carry_the_learned_roof(hass, init_solar) -> None:
    """So a bug report arrives with the geometry that produced it."""
    report = await async_get_config_entry_diagnostics(hass, init_solar)
    model = report["solar_model"]
    assert model is not None
    assert len(model["arrays"]) == 2
    assert model["quality"]["holdout_r2"] > 0.85
    assert len(model["horizon"]) == 12


async def test_diagnostics_without_a_forecast(hass, init_integration) -> None:
    """The key is present and empty rather than missing."""
    report = await async_get_config_entry_diagnostics(hass, init_integration)
    assert report["solar_model"] is None
