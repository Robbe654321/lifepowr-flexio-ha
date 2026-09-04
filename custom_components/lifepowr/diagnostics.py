"""Diagnostics support for LIFEPOWR FlexiO."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import FlexioConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FlexioConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "layout": coordinator.client.layout,
        "last_update_success": coordinator.last_update_success,
        "data": coordinator.data,
    }
