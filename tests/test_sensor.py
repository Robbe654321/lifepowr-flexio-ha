"""Tests for the LIFEPOWR FlexiO sensors."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.lifepowr.api import FlexioConnectionError
from custom_components.lifepowr.const import SCAN_INTERVAL
from homeassistant.const import STATE_UNAVAILABLE
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
    assert hass.states.get("sensor.flexio_solar_production").state == "3.42"

    mock_client.async_get_data.side_effect = FlexioConnectionError
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.flexio_solar_production").state == STATE_UNAVAILABLE

    mock_client.async_get_data.side_effect = None
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.flexio_solar_production").state == "3.42"


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.flexio_solar_production", "3.42"),
        ("sensor.flexio_household_consumption", "1.15"),
        ("sensor.flexio_grid_power", "-2.27"),
        ("sensor.flexio_battery_state_of_charge", "78.0"),
        ("sensor.flexio_electricity_price", "0.1234"),
    ],
)
async def test_sensor_values(hass, init_integration, entity_id, expected) -> None:
    """Values are passed through without rescaling."""
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} was not created"
    assert state.state == expected
