"""Tests for setting up and unloading the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
import pytest

from custom_components.lifepowr.api import FlexioConnectionError, FlexioResponseError


async def test_setup_and_unload(hass, init_integration) -> None:
    """The entry sets up and unloads cleanly."""
    assert init_integration.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize("side_effect", [FlexioConnectionError, FlexioResponseError])
async def test_setup_retries_when_box_unavailable(
    hass, mock_config_entry, mock_client, side_effect
) -> None:
    """An unreachable box leaves the entry in the retry state."""
    mock_client.async_setup.side_effect = side_effect
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_first_refresh_failure_retries(
    hass, mock_config_entry, mock_client
) -> None:
    """A box that answers the probe but not the poll also retries."""
    mock_client.async_get_data.side_effect = FlexioConnectionError
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
