"""Tests for the LIFEPOWR FlexiO sensors."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.lifepowr.api import FlexioConnectionError
from custom_components.lifepowr.const import SCAN_INTERVAL
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    snapshot_platform,
)


async def test_sensors(
    hass,
    init_integration,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """All reported measurements become entities."""
    await snapshot_platform(
        hass, entity_registry, snapshot, init_integration.entry_id
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
