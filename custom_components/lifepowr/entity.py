"""Base entity for the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FlexioClient
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import FlexioCoordinator


def build_device_info(entry_id: str, client: FlexioClient) -> DeviceInfo:
    """Return the device every entity of one entry belongs to.

    The solar forecast entities are fed by a different coordinator -- the sky
    comes from a weather service, not from the box -- but they describe the
    same installation, so they hang off the same device.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=DEFAULT_NAME,
        sw_version=client.version,
        configuration_url=client.base_url.removesuffix("/api"),
    )


class FlexioEntity(CoordinatorEntity[FlexioCoordinator]):
    """Common behaviour for every FlexiO entity."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FlexioCoordinator, description: EntityDescription
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = build_device_info(entry_id, coordinator.client)

    @property
    def _data_key(self) -> str:
        """Return the coordinator key this entity depends on."""
        return self.entity_description.key

    @property
    def available(self) -> bool:
        """Return True when the box last reported this measurement."""
        return (
            super().available
            and self.coordinator.data is not None
            and self._data_key in self.coordinator.data
        )
