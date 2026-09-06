"""Cumulative energy sensors derived from the FlexiObox's live power.

The box reports instantaneous power only, while the Energy dashboard needs
cumulative energy in kWh with a ``total_increasing`` state class. Each sensor
here is a Riemann sum over one direction of one power measurement: the
bidirectional grid and battery flows are split into two positive-only sensors
so importing and exporting never cancel out.

Totals are restored across restarts, so history survives an upgrade or a
reboot. The measurements are filtered and a few seconds apart, so the
trapezoidal rule tracks them closely; a gap longer than
:data:`MAX_SAMPLE_GAP` (the box unreachable, Home Assistant stopped) is not
integrated, because nothing is known about what the power did in between.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from . import api
from .coordinator import FlexioCoordinator
from .entity import FlexioEntity

#: Longer gaps between two samples are treated as missing data rather than
#: integrated. Comfortably above any configurable poll interval, so a slow box
#: or a brief network outage still counts, while a restart does not invent
#: energy.
MAX_SAMPLE_GAP = timedelta(minutes=5)

#: Watt-seconds per kilowatt-hour.
_WS_PER_KWH = 3_600_000.0


def _rising(value: float) -> float:
    """Return the positive part of a signed power reading."""
    return max(value, 0.0)


def _falling(value: float) -> float:
    """Return the magnitude of the negative part of a signed power reading."""
    return max(-value, 0.0)


@dataclass(frozen=True, kw_only=True)
class FlexioEnergySensorEntityDescription(SensorEntityDescription):
    """Describe an energy total derived from one power measurement."""

    #: Coordinator key of the power measurement to integrate.
    source_key: str
    #: Maps the raw API value onto the non-negative power this sensor counts.
    power_fn: Callable[[float], float]


#: The API's load convention signs consumption negative, so importing from the
#: grid and consuming in the house are the falling side of their measurement,
#: while solar production is already positive. Battery power is the one
#: measurement whose raw sign matches Home Assistant: positive is discharging.
#:
#: That battery figure is derived, not reported. ``TotalInvPowerFiltered`` is
#: the inverter's *total* AC power with solar already in it, so integrating it
#: books every sunny hour as a battery discharge -- on a real installation,
#: 77 kWh discharged against 10 kWh charged on a battery of roughly 34 kWh
#: usable. :func:`~.parsing.apply_derived` subtracts PV to get the battery's
#: own flow, and that is what is integrated here.
ENERGY_SENSORS: tuple[FlexioEnergySensorEntityDescription, ...] = (
    FlexioEnergySensorEntityDescription(
        key="pv_energy",
        translation_key="pv_energy",
        source_key=api.KEY_PV_POWER,
        power_fn=_rising,
    ),
    FlexioEnergySensorEntityDescription(
        key="load_energy",
        translation_key="load_energy",
        source_key=api.KEY_LOAD_POWER,
        power_fn=_falling,
    ),
    FlexioEnergySensorEntityDescription(
        key="grid_import_energy",
        translation_key="grid_import_energy",
        source_key=api.KEY_GRID_POWER,
        power_fn=_falling,
    ),
    FlexioEnergySensorEntityDescription(
        key="grid_export_energy",
        translation_key="grid_export_energy",
        source_key=api.KEY_GRID_POWER,
        power_fn=_rising,
    ),
    FlexioEnergySensorEntityDescription(
        key="battery_charge_energy",
        translation_key="battery_charge_energy",
        source_key=api.KEY_BATTERY_POWER,
        power_fn=_falling,
    ),
    FlexioEnergySensorEntityDescription(
        key="battery_discharge_energy",
        translation_key="battery_discharge_energy",
        source_key=api.KEY_BATTERY_POWER,
        power_fn=_rising,
    ),
)


class FlexioEnergySensor(FlexioEntity, RestoreSensor):
    """A kWh total integrated from one direction of one power measurement."""

    entity_description: FlexioEnergySensorEntityDescription

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(
        self,
        coordinator: FlexioCoordinator,
        description: FlexioEnergySensorEntityDescription,
    ) -> None:
        """Initialise the total at zero, pending any restored value."""
        super().__init__(coordinator, description)
        self._total = 0.0
        self._last_power: float | None = None
        self._last_sample: datetime | None = None

    @property
    def _data_key(self) -> str:
        """Track availability of the power measurement being integrated."""
        return self.entity_description.source_key

    async def async_added_to_hass(self) -> None:
        """Restore the previous total and seed the first sample."""
        await super().async_added_to_hass()
        if (
            last_data := await self.async_get_last_sensor_data()
        ) is not None and isinstance(last_data.native_value, (int, float)):
            self._total = float(last_data.native_value)
        self._take_sample()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Add the energy accumulated since the previous sample."""
        self._take_sample()
        super()._handle_coordinator_update()

    @callback
    def _take_sample(self) -> None:
        """Integrate up to the current reading and remember it."""
        description = self.entity_description
        raw = (self.coordinator.data or {}).get(description.source_key)
        if raw is None:
            # Without a reading there is nothing to integrate towards, and the
            # gap must not be bridged once the measurement comes back.
            self._last_power = None
            self._last_sample = None
            return

        power = description.power_fn(raw)
        now = dt_util.utcnow()
        if self._last_power is not None and self._last_sample is not None:
            elapsed = now - self._last_sample
            if timedelta(0) < elapsed <= MAX_SAMPLE_GAP:
                mean_power = (self._last_power + power) / 2
                self._total += mean_power * elapsed.total_seconds() / _WS_PER_KWH

        self._last_power = power
        self._last_sample = now

    @property
    def native_value(self) -> float:
        """Return the accumulated energy in kWh."""
        # Rounded well below the displayed precision, only to keep the stored
        # state free of floating point noise.
        return round(self._total, 6)
