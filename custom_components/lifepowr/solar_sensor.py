"""Sensors for the learned solar forecast.

Two kinds. The forecast sensors answer the question a battery schedule or a
dishwasher timer actually asks -- how much is coming, and when. The model
sensor is the integration showing its work: what it decided the roof looks
like, and how well that decision reproduces days it was never shown.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .solar_forecast import SolarForecast, SolarForecastCoordinator, local_day

_ENERGY: dict[str, Any] = {
    "device_class": SensorDeviceClass.ENERGY,
    "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    "suggested_display_precision": 1,
}


@dataclass(frozen=True, kw_only=True)
class FlexioSolarSensorEntityDescription(SensorEntityDescription):
    """Describe one thing the forecast can be asked."""

    value_fn: Callable[[SolarForecast], StateType | datetime]


def build_descriptions(
    hass: HomeAssistant,
) -> tuple[FlexioSolarSensorEntityDescription, ...]:
    """Return the forecast sensors, bound to the site's own idea of a day.

    "Today" is a local calendar day, while the forecast is a series of UTC
    hours, so every total has to be cut at local midnight rather than at a
    fixed offset -- otherwise the tomorrow figure quietly drifts by an hour
    twice a year.
    """
    return (
        FlexioSolarSensorEntityDescription(
            key="solar_forecast_now",
            translation_key="solar_forecast_now",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            suggested_display_precision=0,
            value_fn=lambda forecast: forecast.power_at(dt_util.utcnow()),
        ),
        FlexioSolarSensorEntityDescription(
            key="solar_forecast_today",
            translation_key="solar_forecast_today",
            value_fn=lambda forecast: forecast.energy(*local_day(hass)),
            **_ENERGY,
        ),
        FlexioSolarSensorEntityDescription(
            key="solar_forecast_remaining_today",
            translation_key="solar_forecast_remaining_today",
            value_fn=lambda forecast: forecast.energy(
                dt_util.utcnow(), local_day(hass)[1]
            ),
            **_ENERGY,
        ),
        FlexioSolarSensorEntityDescription(
            key="solar_forecast_tomorrow",
            translation_key="solar_forecast_tomorrow",
            value_fn=lambda forecast: forecast.energy(*local_day(hass, 1)),
            **_ENERGY,
        ),
        FlexioSolarSensorEntityDescription(
            key="solar_forecast_peak_today",
            translation_key="solar_forecast_peak_today",
            device_class=SensorDeviceClass.TIMESTAMP,
            value_fn=lambda forecast: _peak_time(forecast, hass),
        ),
    )


def _peak_time(forecast: SolarForecast, hass: HomeAssistant) -> datetime | None:
    """Return the hour today's production is expected to peak in."""
    peak = forecast.peak(*local_day(hass))
    return peak[0] if peak else None


MODEL_DESCRIPTION = SensorEntityDescription(
    key="solar_model",
    translation_key="solar_model",
    device_class=SensorDeviceClass.POWER,
    native_unit_of_measurement=UnitOfPower.WATT,
    suggested_display_precision=0,
    entity_category=EntityCategory.DIAGNOSTIC,
)


class FlexioSolarEntity(CoordinatorEntity[SolarForecastCoordinator]):
    """Base for entities fed by the solar coordinator rather than the box."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarForecastCoordinator,
        description: SensorEntityDescription,
        device_info: DeviceInfo,
        entry_id: str,
    ) -> None:
        """Initialise the entity on the shared FlexiO device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info


class FlexioSolarSensor(FlexioSolarEntity, SensorEntity):
    """One question answered from the learned forecast."""

    entity_description: FlexioSolarSensorEntityDescription

    @property
    def available(self) -> bool:
        """Return True once a roof has been learned and a sky fetched."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.available
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the forecast value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class FlexioSolarModelSensor(FlexioSolarEntity, SensorEntity):
    """What the integration fitted, and how well it fits.

    The state is the total learned capacity, and that is the number to trust:
    it is pinned by the brightest hours of the year and can be checked against
    a reference like PVGIS.

    The planes in the attributes are a weaker claim, and worth reading for
    what they are: **the effective plane of each measured source, not a survey
    of the roof.** One inverter often carries panels from more than one roof
    plane, and the single plane that best explains such a mixture is steeper
    and turned further from south than anything actually up there. It forecasts
    that source well -- better, measurably, than the true angles do, since it
    also absorbs the shading -- while describing no real plane.

    Two consequences. Panel counts must not be derived from how the capacity
    splits between these planes; that assumes each plane is one orientation
    with its own honest share of the losses, which a mixture is not. And a
    shallow plane's bearing is barely observable at all: at 14 degrees of tilt
    every bearing from east to west lands within 14% of due south, against 29%
    at 45 degrees, so the fit can be confidently wrong about it.
    """

    @property
    def available(self) -> bool:
        """Return True once a model exists."""
        return self.coordinator.model is not None

    @property
    def native_value(self) -> StateType:
        """Return the total learned capacity in watts."""
        model = self.coordinator.model
        return None if model is None else round(model.peak_power, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the learned planes and the quality of the fit."""
        model = self.coordinator.model
        if model is None:
            return None
        return {
            "arrays": [
                {
                    "orientation": array.orientation,
                    "tilt": round(array.tilt, 1),
                    "azimuth": round(array.azimuth, 1),
                    "peak_power": round(array.peak_power, 1),
                }
                for array in model.arrays
            ],
            "learned_at": model.created.isoformat(),
            "history_days": model.quality.days,
            "held_out_r2": round(model.quality.holdout_r2, 4),
            "rmse": round(model.quality.rmse, 1),
            "ac_limit": None if model.ac_limit is None else round(model.ac_limit, 1),
            # Twelve compass sectors starting at north: how high the trees and
            # roofs in each direction stand, in degrees of sun elevation.
            "skyline": model.horizon.as_list(),
        }
