"""Data update coordinator for LIFEPOWR FlexiO."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FlexioClient, FlexioConnectionError, FlexioError
from .const import DOMAIN, LOGGER, SCAN_INTERVAL

type FlexioConfigEntry = ConfigEntry[FlexioCoordinator]


class FlexioCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Poll a FlexiObox for its live measurements."""

    config_entry: FlexioConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: FlexioConfigEntry,
        client: FlexioClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, float]:
        """Fetch the current measurements."""
        try:
            return await self.client.async_get_data()
        except FlexioConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"host": self.client.host},
            ) from err
        except FlexioError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_response",
            ) from err
