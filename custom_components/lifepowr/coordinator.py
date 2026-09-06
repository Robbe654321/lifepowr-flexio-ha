"""Data update coordinator for LIFEPOWR FlexiO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FlexioClient, FlexioConnectionError, FlexioError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

if TYPE_CHECKING:
    from .solar_forecast import SolarForecastCoordinator

type FlexioConfigEntry = ConfigEntry[FlexioRuntimeData]


@dataclass
class FlexioRuntimeData:
    """Everything one config entry keeps alive.

    The box's own poller and the solar forecast run on different clocks -- one
    every few seconds off the local network, the other every half hour off a
    weather service -- so they are separate coordinators sharing one device.
    """

    coordinator: FlexioCoordinator
    solar: SolarForecastCoordinator | None = None


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
        seconds = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=seconds),
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
