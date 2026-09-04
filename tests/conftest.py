"""Fixtures for the LIFEPOWR FlexiO tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.lifepowr.api import Layout
from custom_components.lifepowr.const import DOMAIN
from homeassistant.const import CONF_HOST

from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"

HOST = "myio.local"

SAMPLE_DATA = {
    "pv_power": 3.42,
    "load_power": 1.15,
    "grid_power": -2.27,
    "inverter_power": 0.85,
    "power_setpoint": 1.0,
    "generic_load_power": 2.0,
    "battery_soc": 78.0,
    "battery_soh": 99.0,
    "battery_voltage": 51.2,
    "battery_current": 16.6,
    "electricity_price": 0.1234,
    "generic_load_max_price": 0.25,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in every test."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mocked config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="FlexiO",
        data={CONF_HOST: HOST},
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
        client.layout = Layout.AGGREGATE
        client.async_detect_layout.return_value = Layout.AGGREGATE
        client.async_get_data.return_value = dict(SAMPLE_DATA)
        yield client


@pytest.fixture
async def init_integration(hass, mock_config_entry, mock_client) -> MockConfigEntry:
    """Set up the integration with a mocked client."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
