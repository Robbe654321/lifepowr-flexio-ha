"""Wiring the roof learner into Home Assistant.

Three jobs, kept apart because they fail independently:

* read the production history out of the recorder and hand it to
  :func:`~.learning.fit` (once a night -- roofs do not move),
* keep the learned model on disk so a restart does not throw away a year of
  evidence,
* pull the coming days' sky from Open-Meteo every half hour and run it through
  the model to get a forecast.

The fit is pure arithmetic over a few thousand samples and takes a second or
two, which is far too long for the event loop, so it runs in an executor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from itertools import pairwise
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    get_metadata,
    statistics_during_period,
)
from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
)
from homeassistant.const import ATTR_DEVICE_CLASS, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    LOGGER,
    MAX_SOLAR_HISTORY_DAYS,
    SOLAR_FORECAST_INTERVAL,
    SOLAR_MODEL_MAX_AGE,
    SOLAR_STORE_KEY,
    SOLAR_STORE_VERSION,
)
from .learning import PowerSample, SolarModel, fit
from .openmeteo import ARCHIVE_LAG, MAX_HISTORY_DAYS, OpenMeteoClient, OpenMeteoError
from .parsing import KEY_PV_POWER

#: Statistics shorter than an hour are not kept forever, so the fit reads the
#: hourly ones that are. An hour is coarse next to the sun's motion, which is
#: why every model value is averaged over the same hour before comparison.
_PERIOD = "hour"

#: Ask for both, because either kind of sensor will do. A power sensor keeps a
#: ``mean``; an energy counter keeps a ``change``, the amount it went up by
#: during the hour. Letting the recorder work the increase out is safer than
#: differencing the running total here, where an off-by-one row would shift
#: every sample an hour and turn the roof fifteen degrees.
_TYPES = {"mean", "change"}

#: Units the statistics are normalised to, whichever the sensor itself uses.
_UNITS = {"energy": "kWh", "power": "W"}

#: Watts that one kilowatt-hour delivered over one hour comes to.
_KWH_PER_HOUR_IN_WATTS = 1000.0

#: Below this the recorder has not yet seen enough of the year.
MIN_HISTORY_HOURS = 200

#: How far Home Assistant may have moved before a stored model is thrown away.
#: A tenth of this is a few kilometres, which changes nothing the sun does.
MAX_SITE_DRIFT = 0.05


@dataclass(frozen=True, slots=True)
class SolarForecast:
    """The coming days' production, hour by hour."""

    #: (interval start, average watts over that hour), in chronological order.
    hours: tuple[tuple[datetime, float], ...] = ()
    model: SolarModel | None = None
    #: Set when the last attempt to reach the weather service failed.
    error: str | None = None

    @property
    def available(self) -> bool:
        """Return True when there is a forecast to report."""
        return bool(self.hours) and self.model is not None

    def energy(self, start: datetime, end: datetime) -> float:
        """Return the energy expected between two moments, kWh.

        Hours are clipped rather than counted whole, so "the rest of today"
        means exactly that even in the middle of an hour.
        """
        total = 0.0
        for hour_start, power in self.hours:
            hour_end = hour_start + timedelta(hours=1)
            overlap = min(hour_end, end) - max(hour_start, start)
            if overlap > timedelta(0):
                total += power * overlap.total_seconds() / 3_600_000.0
        return total

    def power_at(self, when: datetime) -> float | None:
        """Return the power expected at one moment, W.

        The forecast is a series of hourly means, and returning the mean of
        whichever hour contains ``when`` would be defensible and look broken:
        the value would sit perfectly still for an hour and then jump, which
        reads as a sensor that has stopped updating.

        A mean over an hour is, near enough, the instantaneous value at that
        hour's midpoint, so the value between two midpoints is interpolated.
        That both moves the way the sun does and is closer to the truth
        mid-hour than either neighbour.
        """
        if not self.hours:
            return None
        middles = [
            (start + timedelta(minutes=30), power) for start, power in self.hours
        ]
        if when < middles[0][0]:
            # Inside the first hour but before its middle: nothing earlier to
            # interpolate from, so the hour's own mean is the best available.
            return middles[0][1] if when >= self.hours[0][0] else None
        for (before, early), (after, late) in pairwise(middles):
            if before <= when <= after:
                span = (after - before).total_seconds()
                if span <= 0.0:
                    return early
                return early + (late - early) * ((when - before).total_seconds() / span)
        if when <= self.hours[-1][0] + timedelta(hours=1):
            return middles[-1][1]
        return None

    def peak(self, start: datetime, end: datetime) -> tuple[datetime, float] | None:
        """Return when production peaks in a window, and how high."""
        inside = [
            (hour_start, power)
            for hour_start, power in self.hours
            if start <= hour_start < end
        ]
        if not inside:
            return None
        best = max(inside, key=lambda item: item[1])
        return best if best[1] > 0.0 else None


class SolarForecastCoordinator(DataUpdateCoordinator[SolarForecast]):
    """Keep a learned roof model, and a forecast made with it."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Any,
        client: OpenMeteoClient,
        sources: list[str],
        history_days: int,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} solar forecast",
            update_interval=SOLAR_FORECAST_INTERVAL,
        )
        self.client = client
        self.sources = sources
        self.entry_id = config_entry.entry_id
        self.history_days = min(history_days, MAX_SOLAR_HISTORY_DAYS)
        self.model: SolarModel | None = None
        self._store = Store[dict[str, Any]](
            hass,
            SOLAR_STORE_VERSION,
            f"{SOLAR_STORE_KEY}.{config_entry.entry_id}",
        )

    @property
    def statistic_ids(self) -> list[str]:
        """Return the entities whose history the roof is learned from.

        Resolved on use rather than at setup. The FlexiObox's own solar sensor
        is registered by the sensor platform, which is forwarded *after* this
        coordinator is built, so looking it up any earlier finds nothing on a
        fresh install and would postpone the first fit to the next restart.

        More than one is worth having. A site with two inverters read through
        two meters is a strictly richer measurement than their sum -- the same
        roof, described twice instead of once -- and the fit treats each as its
        own set of planes before pooling them.
        """
        if self.sources:
            return list(self.sources)
        own = er.async_get(self.hass).async_get_entity_id(
            SENSOR_DOMAIN, DOMAIN, f"{self.entry_id}_{KEY_PV_POWER}"
        )
        return [own] if own else []

    async def async_load_model(self) -> SolarModel | None:
        """Restore the model learned by a previous run, if it still fits here."""
        stored = await self._store.async_load()
        if not stored:
            return None
        try:
            model = SolarModel.from_dict(stored)
        except (KeyError, TypeError, ValueError):
            LOGGER.warning("Discarding an unreadable stored solar model")
            return None
        # A model is only meaningful where it was learned. If Home Assistant
        # has been moved, the sun no longer stands where the fit assumed.
        if not _same_place(model, self.hass):
            LOGGER.info("The site has moved; the solar model will be relearned")
            return None
        self.model = model
        return model

    @property
    def needs_learning(self) -> bool:
        """Return True when the stored model is missing or stale."""
        return (
            self.model is None
            or dt_util.utcnow() - self.model.created > SOLAR_MODEL_MAX_AGE
        )

    async def async_learn(self) -> SolarModel | None:
        """Read the history, fit the roof, store the result and refresh."""
        samples = await self.async_collect_samples()
        if len(samples) < MIN_HISTORY_HOURS:
            LOGGER.warning(
                "Only %d hours of solar history for %s so far; "
                "the roof cannot be learned yet",
                len(samples),
                ", ".join(self.statistic_ids) or "the solar production sensor",
            )
            return None

        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        model = await self.hass.async_add_executor_job(
            partial(
                fit,
                samples,
                latitude,
                longitude,
                float(self.hass.config.elevation or 0),
            )
        )
        if model is None:
            LOGGER.warning("The solar history did not support a usable model")
            return None

        LOGGER.info(
            "Learned %d roof plane(s), %.2f kWp in total, from %d days "
            "(R² %.3f on days held out of the fit): %s",
            len(model.arrays),
            model.peak_power / 1000,
            model.quality.days,
            model.quality.holdout_r2,
            ", ".join(
                f"{array.orientation} {array.peak_power / 1000:.2f} kWp"
                for array in model.arrays
            ),
        )
        self.model = model
        await self._store.async_save(model.as_dict())
        await self.async_request_refresh()
        return model

    async def async_collect_samples(self) -> list[PowerSample]:
        """Return the measured history, with the sky that produced it.

        The recorder supplies the power. Open-Meteo supplies the irradiance
        that hour actually delivered, which is what lets the fit use every day
        rather than only the cloudless ones -- and removes the clear-sky
        model's beam/diffuse bias from the learned tilt. When the service
        cannot be reached the samples go out bare and :func:`~.learning.fit`
        falls back on its own cloudless-sky model.
        """
        statistic_ids = self.statistic_ids
        if not statistic_ids:
            LOGGER.warning(
                "No solar production sensor to learn from; the roof cannot "
                "be worked out yet"
            )
            return []

        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=self.history_days)
        rows = await get_instance(self.hass).async_add_executor_job(
            partial(
                statistics_during_period,
                self.hass,
                start,
                end,
                set(statistic_ids),
                _PERIOD,
                _UNITS,
                _TYPES,
            )
        )
        if not any(rows.get(statistic_id) for statistic_id in statistic_ids):
            LOGGER.warning(
                "No recorded statistics for %s between %s and %s",
                ", ".join(statistic_ids),
                start,
                end,
            )
            return []

        metadata = await get_instance(self.hass).async_add_executor_job(
            partial(get_metadata, self.hass, statistic_ids=set(statistic_ids))
        )
        sky = await self._async_history_sky(start, end)
        samples: list[PowerSample] = []
        for statistic_id in statistic_ids:
            _, described = metadata.get(statistic_id, (None, None))
            measures_energy = _measures_energy(self.hass, statistic_id, described)
            hourly = _hourly_power(
                rows.get(statistic_id, []), measures_energy=measures_energy
            )
            if rows.get(statistic_id) and not hourly:
                LOGGER.warning(
                    "%s records no usable hourly statistics: it is an %s "
                    "sensor, so the roof needs its hourly increase, which "
                    "Home Assistant only keeps for a total or "
                    "total_increasing state class",
                    statistic_id,
                    "energy" if measures_energy else "unrecognised",
                )
            for hour_start, watts in hourly:
                matched = sky.get(hour_start)
                samples.append(
                    PowerSample(
                        start=hour_start,
                        end=hour_start + timedelta(hours=1),
                        power=watts,
                        source=statistic_id,
                        sky=matched.sky if matched else None,
                        temperature=matched.temperature if matched else None,
                    )
                )
        LOGGER.debug(
            "Collected %d hours of history, %d of them with measured irradiance",
            len(samples),
            sum(1 for sample in samples if sample.sky is not None),
        )
        return samples

    async def _async_history_sky(
        self, start: datetime, end: datetime
    ) -> dict[datetime, Any]:
        """Return the measured sky per hour, empty when it cannot be fetched."""
        first = start.date()
        # The reanalysis trails real time; asking past it returns nothing and
        # would throw away the whole window.
        last = min(end.date(), (dt_util.utcnow() - ARCHIVE_LAG).date())
        if (last - first).days > MAX_HISTORY_DAYS:
            first = last - timedelta(days=MAX_HISTORY_DAYS)
        sky: dict[datetime, Any] = {}
        try:
            for hour in await self.client.async_history(first, last):
                sky[hour.start] = hour
        except OpenMeteoError as err:
            LOGGER.info(
                "No archived irradiance available (%s); "
                "falling back on the cloudless-sky model",
                err,
            )
            return {}

        # The archive stops a few days short of now. The forecast endpoint
        # keeps the recent past, so it covers the seam -- without which the
        # last days of history would arrive bare and take the whole window
        # down to the modelled sky with them.
        catch_up = (end.date() - last).days + 1
        if catch_up > 0:
            try:
                for hour in await self.client.async_forecast(
                    days=1, past_days=catch_up
                ):
                    sky.setdefault(hour.start, hour)
            except OpenMeteoError as err:
                LOGGER.debug("Could not close the archive gap: %s", err)
        return sky

    async def _async_update_data(self) -> SolarForecast:
        """Run the coming days' sky through the learned model."""
        if self.model is None:
            return SolarForecast()
        try:
            hours = await self.client.async_forecast()
        except OpenMeteoError as err:
            LOGGER.debug("Solar forecast update failed: %s", err)
            # Keep yesterday's numbers rather than blanking the dashboard; the
            # entities say plainly that the sky is stale.
            previous = self.data.hours if self.data else ()
            return SolarForecast(hours=previous, model=self.model, error=str(err))

        model = self.model
        return SolarForecast(
            hours=tuple(
                (
                    hour.start,
                    model.power(hour.start, hour.end, hour.sky, hour.temperature),
                )
                for hour in hours
            ),
            model=model,
        )


def _hourly_power(
    series: Sequence[Any], *, measures_energy: bool
) -> list[tuple[datetime, float]]:
    """Return average watts per hour, from a power or an energy statistic.

    Either kind of sensor will do, which matters because the history worth
    learning from is often an old inverter's energy counter rather than a
    power reading. A power sensor keeps an hourly ``mean``, already in watts.
    An energy counter keeps a ``change``, the kilowatt-hours it went up by
    during that hour -- and a kilowatt-hour delivered over one hour is a
    thousand watts, so the conversion is just the scale.

    Which one to read is decided by what the sensor says it measures, never by
    which field happens to be present. An energy counter recorded as a plain
    measurement also keeps a ``mean``, and that mean is the average reading of
    a rising counter: a number that climbs all day and drops at midnight. Read
    as watts it looks exactly like a roof facing west, and the fit would say so
    with a straight face. Better to return nothing and let the caller explain.
    """
    hours: list[tuple[datetime, float]] = []
    for row in series:
        when = _as_datetime(row.get("start"))
        if when is None:
            continue
        if measures_energy:
            if (change := row.get("change")) is not None:
                hours.append((when, max(float(change), 0.0) * _KWH_PER_HOUR_IN_WATTS))
        elif (mean := row.get("mean")) is not None:
            hours.append((when, max(float(mean), 0.0)))
    return hours


def _measures_energy(
    hass: HomeAssistant, entity_id: str, metadata: Any | None = None
) -> bool:
    """Return True when a source counts kilowatt-hours rather than watts.

    The entity is asked first, through the state machine and then the
    registry, because only it distinguishes an energy counter that was
    recorded as a plain measurement -- the case that matters, since such a
    counter keeps a mean that reads convincingly as watts.

    Statistics outlive the entity, though. Replace an inverter and its
    integration goes with it, while years of its history stay in the
    database, so where the entity is gone the statistic's own unit answers
    instead.
    """
    if (state := hass.states.get(entity_id)) is not None and (
        declared := state.attributes.get(ATTR_DEVICE_CLASS)
    ):
        return bool(declared == SensorDeviceClass.ENERGY)
    if (entry := er.async_get(hass).async_get(entity_id)) is not None and (
        device_class := entry.device_class or entry.original_device_class
    ):
        return bool(device_class == SensorDeviceClass.ENERGY)
    if metadata is None:
        return False
    unit = metadata.get("unit_of_measurement")
    if unit in {member.value for member in UnitOfEnergy}:
        return True
    return bool(metadata.get("has_sum"))


def _same_place(model: SolarModel, hass: HomeAssistant) -> bool:
    """Return True when a stored model was learned where Home Assistant is."""
    return (
        abs(model.latitude - hass.config.latitude) < MAX_SITE_DRIFT
        and abs(model.longitude - hass.config.longitude) < MAX_SITE_DRIFT
    )


def _as_datetime(value: Any) -> datetime | None:
    """Return a statistics row's start as an aware datetime."""
    if isinstance(value, datetime):
        return dt_util.as_utc(value)
    if isinstance(value, (int, float)):
        return dt_util.utc_from_timestamp(value)
    return None


def local_day(hass: HomeAssistant, offset: int = 0) -> tuple[datetime, datetime]:
    """Return the start and end of a local day, as aware UTC datetimes."""
    today: date = dt_util.now().date() + timedelta(days=offset)
    start = dt_util.start_of_local_day(today)
    return dt_util.as_utc(start), dt_util.as_utc(start + timedelta(days=1))
