"""Fixtures for the LIFEPOWR FlexiO tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lifepowr.api import Layout
from custom_components.lifepowr.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

HOST = "myio.local"

#: Fixed so the entity unique IDs, which are derived from it, stay stable
#: across runs and can be snapshotted.
ENTRY_ID = "01JQ8Z0000000000000000FLEX"

#: A real sample from a FlexiObox on firmware 1.148.10 (Goodwe GW12K-ET-20),
#: mapped onto the integration's internal keys. The box was importing 5341 W
#: while charging the battery, so grid, load and inverter are all negative in
#: the API's load convention.
SAMPLE_DATA = {
    "pv_power": 1160.6180623644536,
    "load_power": -3002.070671301206,
    "grid_power": -5341.344422408456,
    "inverter_power": -2456.2038037467037,
    "battery_power": -3616.8218661111573,  # inverter - pv
    "generic_load_power": 2811.2092604513246,
    "battery_soc": 18.684592614842874,
    "battery_soh": 100.00000000029866,
    "battery_voltage": 421.3937611738297,
    "battery_current": -8.305514072449588,
    "electricity_price": 0.168179388,
    "generic_load_max_price": 0.0,
    "timestamp": 1788521155668.0,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in every test."""
    return


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Register even the entities that are disabled by default."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
    ):
        yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mocked config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="FlexiO",
        data={CONF_HOST: HOST},
        entry_id=ENTRY_ID,
    )


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Patch the FlexiO client used by both the flow and the setup."""
    with (
        patch(
            "custom_components.lifepowr.FlexioClient", autospec=True
        ) as mock_setup_client,
        patch(
            "custom_components.lifepowr.config_flow.FlexioClient",
            new=mock_setup_client,
        ),
    ):
        client = mock_setup_client.return_value
        client.host = HOST
        client.base_url = f"http://{HOST}/api"
        client.layout = Layout.MEASUREMENTS
        client.version = "1.148.3"
        client.converter = "SolarEdge"
        client.supports_write = True
        client.async_setup.return_value = Layout.MEASUREMENTS
        client.async_get_data.return_value = dict(SAMPLE_DATA)
        client.async_set_generic_load_max_price.return_value = 0.3
        yield client


@pytest.fixture
async def init_integration(hass, mock_config_entry, mock_client) -> MockConfigEntry:
    """Set up the integration with a mocked client."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
