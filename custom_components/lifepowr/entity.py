"""Base entity for the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import FlexioCoordinator


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=DEFAULT_NAME,
            sw_version=coordinator.client.version,
            configuration_url=coordinator.client.base_url.removesuffix("/api"),
        )

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
