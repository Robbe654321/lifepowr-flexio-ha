"""Tests for the LIFEPOWR FlexiO sensors."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.lifepowr.api import FlexioConnectionError
from custom_components.lifepowr.const import SCAN_INTERVAL
from custom_components.lifepowr.energy import MAX_SAMPLE_GAP
from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    Platform,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
    snapshot_platform,
)

from .conftest import SAMPLE_DATA

#: Grid power from the sample, as Home Assistant sees it: the box was
#: importing 5341 W, which the API reports negative.
GRID_IMPORT_W = 5341.344422408456

#: One poll's worth of time, plus a second so the scheduled refresh has
#: certainly fired.
TICK = SCAN_INTERVAL + timedelta(seconds=1)

#: The coordinator spreads its refreshes by a random sub-second offset, so the
#: integrated totals land a fraction of a milliwatt-hour off the nominal
#: period. A hundredth of a watt-hour is well inside that and still far tighter
#: than the three decimals the sensors display.
TOLERANCE_KWH = 1e-5


async def _advance(hass, freezer: FrozenDateTimeFactory, ticks: int) -> timedelta:
    """Run the coordinator for a number of polls and return the time passed."""
    for _ in range(ticks):
        freezer.tick(TICK)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    return ticks * TICK


def _kwh(watts: float, elapsed: timedelta) -> float:
    """Return the energy a constant power delivers over a period."""
    return watts * elapsed.total_seconds() / 3_600_000


@pytest.mark.usefixtures("mock_client", "entity_registry_enabled_by_default")
async def test_sensors(
    hass,
    mock_config_entry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """All reported measurements become entities."""
    # snapshot_platform covers a single platform, so the number entity that
    # the normal setup also creates has to stay out of this one.
    with patch("custom_components.lifepowr.PLATFORMS", [Platform.SENSOR]):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(
        hass, entity_registry, snapshot, mock_config_entry.entry_id
    )


async def test_missing_measurement_is_not_created(
    hass, mock_config_entry, mock_client
) -> None:
    """A box that does not report generic load gets no generic-load entities."""
    data = dict(mock_client.async_get_data.return_value)
    del data["generic_load_max_price"]
    del data["generic_load_power"]
    mock_client.async_get_data.return_value = data

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.flexio_generic_load_available_power") is None
    assert hass.states.get("number.flexio_generic_load_maximum_price") is None
    assert hass.states.get("sensor.flexio_solar_production") is not None


async def test_converter_sensor(hass, init_integration) -> None:
    """The paired converter is exposed as a diagnostic sensor."""
    state = hass.states.get("sensor.flexio_converter")
    assert state is not None
    assert state.state == "SolarEdge"


async def test_converter_sensor_absent_when_unknown(
    hass, mock_config_entry, mock_client
) -> None:
    """A box that does not report a converter gets no converter sensor."""
    mock_client.converter = None
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.flexio_converter") is None


async def test_entities_become_unavailable(
    hass,
    init_integration,
    mock_client,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Losing the box marks the entities unavailable instead of freezing them."""
    solar = "sensor.flexio_solar_production"
    assert float(hass.states.get(solar).state) == pytest.approx(1160.6, abs=0.1)

    mock_client.async_get_data.side_effect = FlexioConnectionError
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(solar).state == STATE_UNAVAILABLE

    mock_client.async_get_data.side_effect = None
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert float(hass.states.get(solar).state) == pytest.approx(1160.6, abs=0.1)


@pytest.mark.parametrize(
    ("entity_id", "expected", "unit"),
    [
        # Solar and battery flow keep the API's sign; the box was charging,
        # hence the negative inverter power.
        ("sensor.flexio_solar_production", 1160.6, UnitOfPower.WATT),
        ("sensor.flexio_inverter_power", -2456.2, UnitOfPower.WATT),
        # Consumption and grid import are negative in the API's load
        # convention and must come out positive.
        ("sensor.flexio_household_consumption", 3002.1, UnitOfPower.WATT),
        ("sensor.flexio_grid_power", 5341.3, UnitOfPower.WATT),
        ("sensor.flexio_battery_state_of_charge", 18.7, PERCENTAGE),
        ("sensor.flexio_battery_voltage", 421.4, UnitOfElectricPotential.VOLT),
        ("sensor.flexio_battery_current", -8.3, UnitOfElectricCurrent.AMPERE),
        ("sensor.flexio_electricity_price", 0.168, "€/kWh"),
    ],
)
async def test_sensor_values(
    hass, init_integration, entity_id, expected, unit
) -> None:
    """Values are reported in watts, with grid and load normalised."""
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} was not created"
    assert float(state.state) == pytest.approx(expected, abs=0.1)
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == unit


async def test_power_is_not_kilowatts(hass, init_integration) -> None:
    """Guard against the website documentation's claim that values are kW.

    A household drawing 5341 kW from the grid is impossible; this test fails
    loudly if the unit is ever changed back.
    """
    state = hass.states.get("sensor.flexio_grid_power")
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UnitOfPower.WATT
    assert abs(float(state.state)) > 1000


async def test_last_measurement_parses_milliseconds(
    hass, init_integration, entity_registry: er.EntityRegistry
) -> None:
    """The box's epoch is in milliseconds and must not land in the far future."""
    entity_id = "sensor.flexio_last_measurement"
    entity_registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state.startswith("2026-")


@pytest.mark.parametrize(
    "entity_id",
    [
        "sensor.flexio_solar_production_energy",
        "sensor.flexio_household_consumption_energy",
        "sensor.flexio_grid_import_energy",
        "sensor.flexio_grid_export_energy",
        "sensor.flexio_battery_charge_energy",
        "sensor.flexio_battery_discharge_energy",
    ],
)
async def test_energy_sensors_are_selectable_in_the_energy_dashboard(
    hass, init_integration, entity_id
) -> None:
    """Every total carries what the Energy dashboard filters on.

    The dashboard only offers sensors whose device class is energy and whose
    state class accumulates; without both, they cannot be picked at all.
    """
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} was not created"
    assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.ENERGY
    assert state.attributes[ATTR_STATE_CLASS] == SensorStateClass.TOTAL_INCREASING
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UnitOfEnergy.KILO_WATT_HOUR
    assert float(state.state) == 0.0


async def test_energy_accumulates_from_power(
    hass, init_integration, freezer: FrozenDateTimeFactory
) -> None:
    """A steady power reading integrates into the matching energy total."""
    elapsed = await _advance(hass, freezer, 4)

    state = hass.states.get("sensor.flexio_grid_import_energy")
    assert float(state.state) == pytest.approx(
        _kwh(GRID_IMPORT_W, elapsed), abs=TOLERANCE_KWH
    )


async def test_opposite_direction_stays_at_zero(
    hass, init_integration, freezer: FrozenDateTimeFactory
) -> None:
    """Importing must not register as exporting, and charging not as discharging.

    The sample has the box importing while charging the battery, so the two
    counter-directions have to stay exactly zero rather than counting the
    flow twice.
    """
    await _advance(hass, freezer, 4)

    assert float(hass.states.get("sensor.flexio_grid_export_energy").state) == 0.0
    assert float(hass.states.get("sensor.flexio_battery_discharge_energy").state) == 0.0
    assert float(hass.states.get("sensor.flexio_battery_charge_energy").state) > 0.0


async def test_long_gap_is_not_integrated(
    hass, init_integration, mock_client, freezer: FrozenDateTimeFactory
) -> None:
    """Nothing is invented for a period the box was unreachable."""
    mock_client.async_get_data.side_effect = FlexioConnectionError
    freezer.tick(MAX_SAMPLE_GAP + timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    mock_client.async_get_data.side_effect = None
    elapsed = await _advance(hass, freezer, 2)

    state = hass.states.get("sensor.flexio_grid_import_energy")
    assert float(state.state) == pytest.approx(
        _kwh(GRID_IMPORT_W, elapsed), abs=TOLERANCE_KWH
    )


async def test_energy_totals_survive_a_restart(
    hass, mock_config_entry, mock_client, freezer: FrozenDateTimeFactory
) -> None:
    """A restored total is carried on rather than restarted from zero."""
    entity_id = "sensor.flexio_grid_import_energy"
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(entity_id, "12.5"),
                {
                    "native_value": 12.5,
                    "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
                },
            ),
        ),
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert float(hass.states.get(entity_id).state) == 12.5

    elapsed = await _advance(hass, freezer, 2)
    assert float(hass.states.get(entity_id).state) == pytest.approx(
        12.5 + _kwh(GRID_IMPORT_W, elapsed), abs=TOLERANCE_KWH
    )


async def test_dropped_measurement_keeps_the_total(
    hass, init_integration, mock_client, freezer: FrozenDateTimeFactory
) -> None:
    """A measurement disappearing does not reset or extrapolate its total."""
    entity_id = "sensor.flexio_grid_import_energy"
    await _advance(hass, freezer, 2)
    accumulated = float(hass.states.get(entity_id).state)
    assert accumulated > 0

    without_grid = dict(mock_client.async_get_data.return_value)
    del without_grid["grid_power"]
    mock_client.async_get_data.return_value = without_grid
    await _advance(hass, freezer, 2)

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    mock_client.async_get_data.return_value = dict(SAMPLE_DATA)
    elapsed = await _advance(hass, freezer, 2)

    # The two polls without a reading are skipped, not bridged: only the time
    # since the measurement came back is integrated.
    assert float(hass.states.get(entity_id).state) == pytest.approx(
        accumulated + _kwh(GRID_IMPORT_W, elapsed - TICK), abs=TOLERANCE_KWH
    )
