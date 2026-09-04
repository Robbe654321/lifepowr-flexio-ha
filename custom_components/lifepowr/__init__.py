"""The LIFEPOWR FlexiO integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FlexioClient, FlexioConnectionError, FlexioError
from .const import DOMAIN
from .coordinator import FlexioConfigEntry, FlexioCoordinator

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: FlexioConfigEntry) -> bool:
    """Set up LIFEPOWR FlexiO from a config entry."""
    client = FlexioClient(async_get_clientsession(hass), entry.data[CONF_HOST])

    try:
        await client.async_setup()
    except FlexioConnectionError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": client.host},
        ) from err
    except FlexioError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="invalid_response",
        ) from err

    coordinator = FlexioCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FlexioConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
