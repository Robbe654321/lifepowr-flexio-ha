"""The LIFEPOWR FlexiO integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .api import FlexioClient, FlexioConnectionError, FlexioError
from .const import (
    CONF_SOLAR_FORECAST,
    CONF_SOLAR_HISTORY_DAYS,
    CONF_SOLAR_SOURCE,
    DEFAULT_SOLAR_FORECAST,
    DEFAULT_SOLAR_HISTORY_DAYS,
    DOMAIN,
    LOGGER,
    SERVICE_LEARN_SOLAR_MODEL,
    SOLAR_LEARN_HOUR,
)
from .coordinator import FlexioConfigEntry, FlexioCoordinator, FlexioRuntimeData
from .openmeteo import OpenMeteoClient
from .solar_forecast import SolarForecastCoordinator

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's service actions.

    Done here rather than per entry so the action exists whether or not a
    FlexiObox happens to be loaded, and can say plainly why it cannot run.
    """
    _async_register_services(hass)
    return True


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

    entry.runtime_data = FlexioRuntimeData(coordinator=coordinator)
    if entry.options.get(CONF_SOLAR_FORECAST, DEFAULT_SOLAR_FORECAST):
        entry.runtime_data.solar = await _async_setup_solar(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Only now does the box's own solar sensor exist in the entity registry,
    # and that is the history the roof is learned from. Starting the fit any
    # earlier finds nothing on a fresh install.
    if (solar := entry.runtime_data.solar) is not None and solar.needs_learning:
        entry.async_create_background_task(
            hass, solar.async_learn(), f"{DOMAIN} learn solar model"
        )

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_setup_solar(
    hass: HomeAssistant, entry: FlexioConfigEntry
) -> SolarForecastCoordinator | None:
    """Start the roof learner and the forecast, if it can be started at all."""
    if "recorder" not in hass.config.components:
        LOGGER.warning(
            "The solar forecast needs the recorder, which is not set up; "
            "no roof will be learned"
        )
        return None

    solar = SolarForecastCoordinator(
        hass,
        entry,
        OpenMeteoClient(
            async_get_clientsession(hass),
            hass.config.latitude,
            hass.config.longitude,
        ),
        _solar_sources(entry),
        entry.options.get(CONF_SOLAR_HISTORY_DAYS, DEFAULT_SOLAR_HISTORY_DAYS),
    )
    await solar.async_load_model()

    # A roof does not move, so the fit runs once a night rather than on the
    # coordinator's interval. Anything missing at startup is caught up on.
    entry.async_on_unload(
        async_track_time_change(
            hass,
            _learn_at_night(solar),
            hour=SOLAR_LEARN_HOUR,
            minute=0,
            second=0,
        )
    )
    # A model restored from disk can start forecasting straight away; a
    # missing one waits for the fit, which runs once the platforms are up.
    if not solar.needs_learning:
        await solar.async_refresh()
    return solar


def _learn_at_night(
    solar: SolarForecastCoordinator,
) -> Callable[[datetime], Awaitable[None]]:
    """Return the nightly callback that refits the roof."""

    async def _learn(_now: datetime) -> None:
        await solar.async_learn()

    return _learn


def _solar_sources(entry: FlexioConfigEntry) -> list[str]:
    """Return the entities the roof should be learned from.

    Stored as a list, but an entry configured before the option accepted more
    than one holds a bare string, and reloading must not lose it.
    """
    configured = entry.options.get(CONF_SOLAR_SOURCE) or []
    if isinstance(configured, str):
        return [configured]
    return [str(item) for item in configured]


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's services once."""
    if hass.services.has_service(DOMAIN, SERVICE_LEARN_SOLAR_MODEL):
        return

    async def _async_learn(call: ServiceCall) -> None:
        """Relearn the roof now, for every entry that has a forecast."""
        learned = False
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            solar = getattr(entry.runtime_data, "solar", None)
            if solar is None:
                continue
            learned = True
            await solar.async_learn()
        if not learned:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="solar_forecast_disabled",
            )

    hass.services.async_register(
        DOMAIN, SERVICE_LEARN_SOLAR_MODEL, _async_learn, schema=vol.Schema({})
    )


async def _async_reload_entry(hass: HomeAssistant, entry: FlexioConfigEntry) -> None:
    """Apply changed options by reloading."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FlexioConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
