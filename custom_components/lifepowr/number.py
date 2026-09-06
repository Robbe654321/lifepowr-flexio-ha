"""Number platform for the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import api
from .const import DOMAIN
from .coordinator import FlexioConfigEntry
from .entity import FlexioEntity
from .sensor import CURRENCY_PER_KWH

#: Writes go to a single device; serialise them.
PARALLEL_UPDATES = 1

#: The box rejects negative prices with HTTP 400. The upper bound is not
#: specified by the API, so this is a generous sanity limit.
MAX_PRICE = 5.0

MAX_PRICE_DESCRIPTION = NumberEntityDescription(
    key=api.KEY_GENERIC_LOAD_MAX_PRICE,
    translation_key="generic_load_max_price",
    native_min_value=0,
    native_max_value=MAX_PRICE,
    native_step=0.001,
    native_unit_of_measurement=CURRENCY_PER_KWH,
    mode=NumberMode.BOX,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlexioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the FlexiO number entities."""
    coordinator = entry.runtime_data.coordinator
    if (
        coordinator.client.supports_write
        and MAX_PRICE_DESCRIPTION.key in coordinator.data
    ):
        async_add_entities([FlexioMaxPriceNumber(coordinator, MAX_PRICE_DESCRIPTION)])


class FlexioMaxPriceNumber(FlexioEntity, NumberEntity):
    """The price above which the generic load is not allowed to run."""

    entity_description: NumberEntityDescription

    @property
    def native_value(self) -> float | None:
        """Return the price cap currently set on the box."""
        return self.coordinator.data.get(self.entity_description.key)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new price cap to the box."""
        try:
            await self.coordinator.client.async_set_generic_load_max_price(value)
        except api.FlexioValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_price",
                translation_placeholders={"price": str(value)},
            ) from err
        except api.FlexioError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"host": self.coordinator.client.host},
            ) from err

        await self.coordinator.async_request_refresh()
