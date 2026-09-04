"""Tests for the LIFEPOWR FlexiO config flow."""

from __future__ import annotations

import pytest

from custom_components.lifepowr.api import FlexioConnectionError, FlexioResponseError
from custom_components.lifepowr.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType

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
    mock_client.async_detect_layout.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_client.async_detect_layout.side_effect = None
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
    mock_client.async_detect_layout.side_effect = FlexioConnectionError

    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert init_integration.data[CONF_HOST] == HOST
