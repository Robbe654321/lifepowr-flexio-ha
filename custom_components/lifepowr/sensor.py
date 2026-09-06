"""Sensor platform for the LIFEPOWR FlexiO integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import api
from .coordinator import FlexioConfigEntry, FlexioCoordinator
from .energy import ENERGY_SENSORS, FlexioEnergySensor
from .entity import FlexioEntity

PARALLEL_UPDATES = 0

CURRENCY_PER_KWH = "€/kWh"


def _as_timestamp(value: float) -> datetime | None:
    """Convert the box's epoch into an aware datetime."""
    if (seconds := api.normalise_timestamp(value)) is None:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def _invert(value: float) -> float:
    """Flip the box's load convention to Home Assistant's.

    The API signs consumption negative: importing from the grid and consuming
    in the house are both reported as negative numbers. Home Assistant expects
    the opposite for these two, so they are negated. Battery flow keeps the
    raw sign, where positive already means discharging, and solar production
    is already positive.
    """
    return -value


@dataclass(frozen=True, kw_only=True)
class FlexioSensorEntityDescription(SensorEntityDescription):
    """Describe a FlexiO sensor."""

    value_fn: Callable[[float], StateType | datetime] = lambda value: value


#: The box reports watts, despite the website documentation claiming kW.
POWER_SENSOR: dict[str, Any] = {
    "device_class": SensorDeviceClass.POWER,
    "state_class": SensorStateClass.MEASUREMENT,
    "native_unit_of_measurement": UnitOfPower.WATT,
    "suggested_display_precision": 0,
}

SENSORS: tuple[FlexioSensorEntityDescription, ...] = (
    FlexioSensorEntityDescription(
        key=api.KEY_PV_POWER, translation_key="pv_power", **POWER_SENSOR
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_LOAD_POWER,
        translation_key="load_power",
        value_fn=_invert,
        **POWER_SENSOR,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_GRID_POWER,
        translation_key="grid_power",
        value_fn=_invert,
        **POWER_SENSOR,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_BATTERY_POWER, translation_key="battery_power", **POWER_SENSOR
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_INVERTER_POWER, translation_key="inverter_power", **POWER_SENSOR
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_POWER_SETPOINT, translation_key="power_setpoint", **POWER_SENSOR
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_GENERIC_LOAD_POWER,
        translation_key="generic_load_power",
        **POWER_SENSOR,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_BATTERY_SOC,
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_BATTERY_SOH,
        translation_key="battery_soh",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_BATTERY_VOLTAGE,
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_BATTERY_CURRENT,
        translation_key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_ELECTRICITY_PRICE,
        translation_key="electricity_price",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CURRENCY_PER_KWH,
        suggested_display_precision=4,
    ),
    FlexioSensorEntityDescription(
        key=api.KEY_TIMESTAMP,
        translation_key="last_measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_as_timestamp,
    ),
)

CONVERTER_DESCRIPTION = SensorEntityDescription(
    key="converter",
    translation_key="converter",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlexioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the FlexiO sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        FlexioSensor(coordinator, description)
        for description in SENSORS
        if description.key in coordinator.data
    ]
    # The box reports power only, so the Energy dashboard's kWh totals are
    # integrated here rather than left to the user's own template sensors.
    entities += [
        FlexioEnergySensor(coordinator, description)
        for description in ENERGY_SENSORS
        if description.source_key in coordinator.data
    ]
    if coordinator.client.converter is not None:
        entities.append(FlexioConverterSensor(coordinator, CONVERTER_DESCRIPTION))
    async_add_entities(entities)


class FlexioSensor(FlexioEntity, SensorEntity):
    """A single measurement reported by the FlexiObox."""

    entity_description: FlexioSensorEntityDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current measurement."""
        if (value := self.coordinator.data.get(self.entity_description.key)) is None:
            return None
        return self.entity_description.value_fn(value)


class FlexioConverterSensor(FlexioEntity, SensorEntity):
    """The converter the FlexiObox is paired with."""

    def __init__(
        self, coordinator: FlexioCoordinator, description: SensorEntityDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description)
        self._attr_native_value = coordinator.client.converter

    @property
    def available(self) -> bool:
        """Return True while the coordinator is healthy.

        The converter is read once at setup and does not appear in the polled
        data, so the key-presence check of the base class does not apply.
        """
        return self.coordinator.last_update_success
