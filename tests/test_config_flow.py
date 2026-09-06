"""Tests for the LIFEPOWR FlexiO config flow."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.lifepowr.api import FlexioConnectionError, FlexioResponseError
from custom_components.lifepowr.const import (
    CONF_SOLAR_FORECAST,
    CONF_SOLAR_HISTORY_DAYS,
    DEFAULT_SOLAR_HISTORY_DAYS,
    DOMAIN,
)

from .conftest import HOST


async def test_user_flow(hass, mock_client) -> None:
    """A reachable box creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST}


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (FlexioConnectionError, "cannot_connect"),
        (FlexioResponseError, "invalid_response"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors(hass, mock_client, side_effect, error) -> None:
    """Errors are shown on the form and the flow can be retried."""
    mock_client.async_setup.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_client.async_setup.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_host_aborts(hass, mock_client, mock_config_entry) -> None:
    """The same host cannot be configured twice."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass, mock_client, init_integration) -> None:
    """The host can be changed on an existing entry."""
    result = await init_integration.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.20"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data[CONF_HOST] == "192.168.1.20"


async def test_reconfigure_error(hass, mock_client, init_integration) -> None:
    """An unreachable new host keeps the old configuration."""
    mock_client.async_setup.side_effect = FlexioConnectionError

    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert init_integration.data[CONF_HOST] == HOST


async def test_options_flow_changes_poll_interval(
    hass, mock_client, init_integration
) -> None:
    """The poll interval is configurable and takes effect on reload."""
    coordinator = init_integration.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(seconds=10)

    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 3}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The solar options keep their defaults when the form leaves them alone.
    assert init_integration.options == {
        CONF_SCAN_INTERVAL: 3,
        CONF_SOLAR_FORECAST: False,
        CONF_SOLAR_HISTORY_DAYS: DEFAULT_SOLAR_HISTORY_DAYS,
    }
    assert init_integration.runtime_data.coordinator.update_interval == timedelta(
        seconds=3
    )
