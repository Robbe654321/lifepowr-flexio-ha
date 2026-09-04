"""Tests for the LIFEPOWR FlexiO generic load price cap."""

from __future__ import annotations

import pytest

from custom_components.lifepowr.api import FlexioConnectionError, FlexioValueError
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

ENTITY_ID = "number.flexio_generic_load_maximum_price"


async def _set(hass, value: float) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: value},
        blocking=True,
    )


async def test_state(hass, init_integration) -> None:
    """The current cap is exposed as the entity state."""
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "0.25"


async def test_set_value(hass, init_integration, mock_client) -> None:
    """Setting the value posts to the box and refreshes."""
    await _set(hass, 0.3)
    mock_client.async_set_generic_load_max_price.assert_awaited_once_with(0.3)


async def test_rejected_price_raises_validation_error(
    hass, init_integration, mock_client
) -> None:
    """A price the box refuses surfaces as a validation error."""
    mock_client.async_set_generic_load_max_price.side_effect = FlexioValueError

    with pytest.raises(ServiceValidationError):
        await _set(hass, 0.3)


async def test_unreachable_box_raises_home_assistant_error(
    hass, init_integration, mock_client
) -> None:
    """A failed write surfaces as a Home Assistant error."""
    mock_client.async_set_generic_load_max_price.side_effect = FlexioConnectionError

    with pytest.raises(HomeAssistantError):
        await _set(hass, 0.3)


async def test_not_created_without_write_support(
    hass, mock_config_entry, mock_client
) -> None:
    """A legacy firmware gets no writable entity."""
    mock_client.supports_write = False
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID) is None
