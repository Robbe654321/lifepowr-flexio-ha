"""Diagnostics support for LIFEPOWR FlexiO."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import FlexioConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FlexioConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    return {
        "layout": coordinator.client.layout,
        "version": coordinator.client.version,
        "converter": coordinator.client.converter,
        "supports_write": coordinator.client.supports_write,
        "last_update_success": coordinator.last_update_success,
        "data": coordinator.data,
    }
