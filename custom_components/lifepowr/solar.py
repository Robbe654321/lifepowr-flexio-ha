"""Solar geometry and irradiance maths for the FlexiO solar forecast.

Like :mod:`parsing`, this module deliberately depends on nothing beyond the
standard library, so the maths can be checked without Home Assistant
installed. It answers three questions:

* where is the sun (:func:`solar_position`),
* what would a cloudless sky deliver (:func:`clear_sky`),
* how much of a given sky lands on a tilted roof (:func:`plane_of_array`).

Angles are degrees throughout. Azimuths are compass bearings -- 0 is north,
90 east, 180 south, 270 west -- for both the sun and the roof, because that is
the convention Home Assistant, Open-Meteo and most roof owners use.

The algorithms are the standard ones: NOAA's solar position equations, the
Ineichen-Perez clear-sky model, and the Hay-Davies-Klucher-Reindl
transposition. None of them is exact, but the fit in :mod:`learning` scales
whatever they return, so a systematic few percent is absorbed into the learned
capacity rather than showing up in the forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
from typing import Final

#: Solar constant, W/m². The 2015 IAU value.
SOLAR_CONSTANT: Final = 1361.0

#: Linke turbidity for a hazy-but-clear north-western European sky. The clear
#: sky model is only ever used relatively -- to spot cloudless periods and as
#: an offline fallback -- so this does not need to be a local measurement.
DEFAULT_LINKE_TURBIDITY: Final = 3.0

#: Fraction of ground-reflected light. Grass and tiles alike sit near this.
DEFAULT_ALBEDO: Final = 0.2

#: Yearly mean and swing of the Linke turbidity climatology below.
_LINKE_MEAN: Final = 3.6
_LINKE_SWING: Final = 0.9

#: Day of the year the atmosphere is haziest, in the northern hemisphere.
_LINKE_PEAK_DAY: Final = 197


def linke_turbidity(day_of_year: int, latitude: float) -> float:
    """Return a climatological Linke turbidity for a date and hemisphere.

    Turbidity is how much haze, water vapour and aerosol stand between the
    panels and the sun. It is the single number that decides how a cloudless
    sky splits into a hard beam and a soft glow off the rest of the sky, and
    getting it wrong tilts the learned roof: a sky modelled as too clear has
    to be explained by panels standing too steeply.

    It also swings with the season -- summer air over north-western Europe
    carries roughly twice the haze of a cold January morning -- so a single
    annual value biases the seasonal shape that the tilt is read from.
    """
    phase = 2.0 * math.pi * (day_of_year - _LINKE_PEAK_DAY) / 365.0
    if latitude < 0:
        phase += math.pi
    return _LINKE_MEAN + _LINKE_SWING * math.cos(phase)

#: ASHRAE incidence angle modifier coefficient for ordinary glass.
_IAM_B0: Final = 0.05

#: Below this elevation the sun contributes nothing worth modelling, and the
#: air mass and transposition formulas stop behaving.
MIN_ELEVATION: Final = 1.0

_JULIAN_UNIX_EPOCH: Final = 2440587.5
_SECONDS_PER_DAY: Final = 86400.0


@dataclass(frozen=True, slots=True)
class SolarPosition:
    """Where the sun is, seen from one place at one moment."""

    #: Angle from straight up, degrees. 90 is the horizon.
    zenith: float
    #: Compass bearing of the sun, degrees clockwise from north.
    azimuth: float
    #: Day of the year, kept so the extraterrestrial irradiance can be scaled.
    day_of_year: int

    @property
    def elevation(self) -> float:
        """Return the sun's height above the horizon in degrees."""
        return 90.0 - self.zenith

    @property
    def cos_zenith(self) -> float:
        """Return cos(zenith), floored at zero below the horizon."""
        return max(math.cos(math.radians(self.zenith)), 0.0)

    @property
    def is_up(self) -> bool:
        """Return True when the sun is high enough to model."""
        return self.elevation >= MIN_ELEVATION


@dataclass(frozen=True, slots=True)
class Irradiance:
    """A sky, split into the three components a tilted plane sees differently.

    All in W/m²: ``ghi`` on the horizontal, ``dni`` on a plane tracking the
    sun, ``dhi`` the horizontal share arriving from the rest of the sky.
    """

    ghi: float
    dni: float
    dhi: float

    def scaled(self, factor: float) -> Irradiance:
        """Return this sky with every component multiplied by ``factor``."""
        return Irradiance(self.ghi * factor, self.dni * factor, self.dhi * factor)


#: A completely dark sky, returned whenever the sun is down.
DARK: Final = Irradiance(0.0, 0.0, 0.0)


def extraterrestrial_irradiance(day_of_year: int) -> float:
    """Return the solar constant corrected for the Earth's orbit, W/m²."""
    angle = 2.0 * math.pi * (day_of_year - 1) / 365.0
    return SOLAR_CONSTANT * (1.0 + 0.033 * math.cos(angle))


def _julian_century(when: datetime) -> float:
    """Return the Julian centuries since J2000.0 for an aware datetime."""
    timestamp = when.astimezone(UTC).timestamp()
    julian_day = timestamp / _SECONDS_PER_DAY + _JULIAN_UNIX_EPOCH
    return (julian_day - 2451545.0) / 36525.0


def solar_position(
    when: datetime, latitude: float, longitude: float
) -> SolarPosition:
    """Return the sun's position, following NOAA's solar position equations.

    Accurate to well under a tenth of a degree for any date this integration
    will ever see, which is far finer than the roof geometry being learned.
    """
    when = when.astimezone(UTC)
    century = _julian_century(when)

    mean_longitude = (
        280.46646 + century * (36000.76983 + century * 0.0003032)
    ) % 360.0
    mean_anomaly = 357.52911 + century * (35999.05029 - 0.0001537 * century)
    eccentricity = 0.016708634 - century * (0.000042037 + 0.0000001267 * century)

    anomaly_rad = math.radians(mean_anomaly)
    centre = (
        math.sin(anomaly_rad) * (1.914602 - century * (0.004817 + 0.000014 * century))
        + math.sin(2 * anomaly_rad) * (0.019993 - 0.000101 * century)
        + math.sin(3 * anomaly_rad) * 0.000289
    )
    true_longitude = mean_longitude + centre
    omega = 125.04 - 1934.136 * century
    apparent_longitude = (
        true_longitude - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    )

    mean_obliquity = 23.0 + (
        26.0 + (21.448 - century * (46.815 + century * (0.00059 - century * 0.001813)))
        / 60.0
    ) / 60.0
    obliquity = mean_obliquity + 0.00256 * math.cos(math.radians(omega))

    declination = math.asin(
        math.sin(math.radians(obliquity)) * math.sin(math.radians(apparent_longitude))
    )

    vary = math.tan(math.radians(obliquity / 2.0)) ** 2
    mean_longitude_rad = math.radians(mean_longitude)
    equation_of_time = 4.0 * math.degrees(
        vary * math.sin(2 * mean_longitude_rad)
        - 2 * eccentricity * math.sin(anomaly_rad)
        + 4
        * eccentricity
        * vary
        * math.sin(anomaly_rad)
        * math.cos(2 * mean_longitude_rad)
        - 0.5 * vary * vary * math.sin(4 * mean_longitude_rad)
        - 1.25 * eccentricity * eccentricity * math.sin(2 * anomaly_rad)
    )

    minutes = when.hour * 60.0 + when.minute + when.second / 60.0
    true_solar_time = (minutes + equation_of_time + 4.0 * longitude) % 1440.0
    hour_angle = math.radians(true_solar_time / 4.0 - 180.0)

    latitude_rad = math.radians(latitude)
    cos_zenith = math.sin(latitude_rad) * math.sin(declination) + math.cos(
        latitude_rad
    ) * math.cos(declination) * math.cos(hour_angle)
    cos_zenith = min(max(cos_zenith, -1.0), 1.0)
    zenith = math.degrees(math.acos(cos_zenith))

    # Bearing measured from due south, positive towards the west, then turned
    # into a compass bearing. Using atan2 keeps it single-valued across noon
    # and through the cases where the midday sun stands north of overhead.
    azimuth = 180.0 + math.degrees(
        math.atan2(
            math.sin(hour_angle),
            math.cos(hour_angle) * math.sin(latitude_rad)
            - math.tan(declination) * math.cos(latitude_rad),
        )
    )

    return SolarPosition(
        zenith=zenith - _refraction(90.0 - zenith),
        azimuth=azimuth % 360.0,
        day_of_year=when.timetuple().tm_yday,
    )


def _refraction(elevation: float) -> float:
    """Return the degrees the atmosphere lifts the sun by, at ``elevation``."""
    if elevation > 85.0:
        return 0.0
    if elevation > 5.0:
        tan_e = math.tan(math.radians(elevation))
        arcseconds = (
            58.1 / tan_e - 0.07 / tan_e**3 + 0.000086 / tan_e**5
        )
    elif elevation > -0.575:
        arcseconds = 1735.0 + elevation * (
            -518.2 + elevation * (103.4 + elevation * (-12.79 + elevation * 0.711))
        )
    else:
        arcseconds = -20.774 / math.tan(math.radians(max(elevation, -1.0)))
    return arcseconds / 3600.0


def air_mass(zenith: float, altitude: float = 0.0) -> float:
    """Return the pressure-corrected relative air mass (Kasten-Young)."""
    zenith = min(zenith, 90.0)
    relative = 1.0 / (
        math.cos(math.radians(zenith))
        + 0.50572 * (96.07995 - zenith) ** -1.6364
    )
    # Barometric pressure ratio for the site's height above sea level.
    return relative * math.exp(-altitude / 8434.5)


def clear_sky(
    position: SolarPosition,
    altitude: float = 0.0,
    linke: float = DEFAULT_LINKE_TURBIDITY,
) -> Irradiance:
    """Return the Ineichen-Perez cloudless sky for a solar position."""
    if not position.is_up:
        return DARK

    cos_zenith = position.cos_zenith
    mass = air_mass(position.zenith, altitude)
    extra = extraterrestrial_irradiance(position.day_of_year)

    fh1 = math.exp(-altitude / 8000.0)
    fh2 = math.exp(-altitude / 1250.0)
    cg1 = 5.09e-5 * altitude + 0.868
    cg2 = 3.92e-5 * altitude + 0.0387

    ghi = (
        cg1
        * extra
        * cos_zenith
        * math.exp(-cg2 * mass * (fh1 + fh2 * (linke - 1.0)))
        * math.exp(0.01 * mass**1.8)
    )
    ghi = max(ghi, 0.0)

    beam = 0.664 + 0.163 / fh1
    dni_direct = extra * max(beam * math.exp(-0.09 * mass * (linke - 1.0)), 0.0)
    # Perez's empirical cap, which keeps low sun angles from running away.
    capped = ghi * max(
        1.0 - (0.1 - 0.2 * math.exp(-linke)) / (0.1 + 0.882 / fh1), 0.0
    ) / cos_zenith
    dni = min(dni_direct, capped)

    return Irradiance(ghi=ghi, dni=dni, dhi=max(ghi - dni * cos_zenith, 0.0))


#: Compass sectors the learned skyline is divided into.
HORIZON_SECTORS: Final = 12

_SECTOR_WIDTH: Final = 360.0 / HORIZON_SECTORS

#: Degrees of sun elevation over which an obstruction goes from blocking the
#: beam entirely to not at all. Real skylines are ragged, the sun is half a
#: degree wide, and a measurement is an average over a whole hour, so the edge
#: is always soft.
HORIZON_SOFTNESS: Final = 4.0


@dataclass(frozen=True, slots=True)
class Horizon:
    """How high the skyline stands in each direction, degrees of elevation.

    Trees, a neighbour's gable and the hill behind the house take the first and
    last hour of production away, and no amount of tilt or azimuth can express
    that -- a model without a skyline explains the missing evening by claiming
    the panels face east. One elevation per compass sector, learned from the
    same history as the panels themselves.
    """

    elevations: tuple[float, ...]

    @classmethod
    def flat(cls) -> Horizon:
        """Return an unobstructed skyline."""
        return cls((0.0,) * HORIZON_SECTORS)

    @property
    def is_flat(self) -> bool:
        """Return True when nothing is blocking anything."""
        return not any(self.elevations)

    def elevation_at(self, azimuth: float) -> float:
        """Return the skyline height in one direction, interpolated."""
        offset = (azimuth % 360.0) / _SECTOR_WIDTH - 0.5
        lower = math.floor(offset)
        fraction = offset - lower
        first = self.elevations[lower % HORIZON_SECTORS]
        second = self.elevations[(lower + 1) % HORIZON_SECTORS]
        return first + (second - first) * fraction

    def transmission(self, position: SolarPosition) -> float:
        """Return the share of direct sunlight that clears the skyline."""
        if self.is_flat:
            return 1.0
        above = position.elevation - self.elevation_at(position.azimuth)
        return min(max(above / HORIZON_SOFTNESS, 0.0), 1.0)

    def as_list(self) -> list[float]:
        """Return the skyline as plain data for storage."""
        return [round(value, 1) for value in self.elevations]


def sector_weights(azimuth: float) -> tuple[int, float]:
    """Return the sector below an azimuth and how far past it the azimuth sits.

    Splitting the interpolation out this way lets a fit try thousands of
    candidate skylines against one precomputed set of sun positions.
    """
    offset = (azimuth % 360.0) / _SECTOR_WIDTH - 0.5
    lower = math.floor(offset)
    return lower % HORIZON_SECTORS, offset - lower


def incidence_angle(tilt: float, azimuth: float, position: SolarPosition) -> float:
    """Return the angle between the sun and a roof plane's normal, degrees."""
    return math.degrees(math.acos(min(max(
        _cos_incidence(tilt, azimuth, position), -1.0), 1.0)))


def _cos_incidence(
    tilt: float, azimuth: float, position: SolarPosition
) -> float:
    """Return the cosine of the angle of incidence on a tilted plane."""
    tilt_rad = math.radians(tilt)
    zenith_rad = math.radians(position.zenith)
    return math.cos(zenith_rad) * math.cos(tilt_rad) + math.sin(zenith_rad) * math.sin(
        tilt_rad
    ) * math.cos(math.radians(position.azimuth - azimuth))


def incidence_angle_modifier(cos_aoi: float) -> float:
    """Return the share of beam light that a glass cover lets through.

    ASHRAE's one-parameter model. At noon on a well-aimed roof this is
    essentially 1; at a grazing morning angle it removes the reflection that
    a plain cosine would wrongly count as production.
    """
    if cos_aoi <= 0.0:
        return 0.0
    return min(max(1.0 - _IAM_B0 * (1.0 / cos_aoi - 1.0), 0.0), 1.0)


def beam_on_plane(
    tilt: float, azimuth: float, position: SolarPosition, sky: Irradiance
) -> float:
    """Return the direct sunlight landing on a tilted plane, W/m².

    Separate from :func:`plane_of_array` because it is the only part a
    skyline blocks, and the fit needs to scale it on its own.
    """
    cos_aoi = max(_cos_incidence(tilt, azimuth, position), 0.0)
    return sky.dni * cos_aoi * incidence_angle_modifier(cos_aoi)


def plane_of_array(
    tilt: float,
    azimuth: float,
    position: SolarPosition,
    sky: Irradiance,
    albedo: float = DEFAULT_ALBEDO,
    horizon: Horizon | None = None,
) -> float:
    """Return the irradiance reaching a tilted plane, W/m².

    Hay-Davies-Klucher-Reindl: the beam is projected geometrically, the
    diffuse sky is split into a circumsolar part that follows the sun and an
    isotropic part brightened towards the horizon, and the ground reflects a
    share of the horizontal total back up under the panels.

    A ``horizon`` blocks the direct beam while the sun is behind it. The
    diffuse and reflected shares are left alone: an obstruction that hides the
    sun still leaves most of the sky, which is why a shaded panel goes quiet
    rather than dark.
    """
    if not position.is_up or sky.ghi <= 0.0:
        return 0.0

    cos_aoi = max(_cos_incidence(tilt, azimuth, position), 0.0)
    cos_zenith = max(position.cos_zenith, math.cos(math.radians(89.0)))
    tilt_rad = math.radians(tilt)

    beam = beam_on_plane(tilt, azimuth, position, sky)
    if horizon is not None:
        beam *= horizon.transmission(position)

    # Anisotropy index: how much of the diffuse light is really circumsolar.
    extra = extraterrestrial_irradiance(position.day_of_year)
    anisotropy = min(max(sky.dni / extra, 0.0), 1.0)
    ratio = cos_aoi / cos_zenith
    horizon_brightening = math.sqrt(
        min(max(sky.dni * cos_zenith / sky.ghi, 0.0), 1.0)
    )
    diffuse = sky.dhi * (
        anisotropy * ratio
        + (1.0 - anisotropy)
        * (1.0 + math.cos(tilt_rad))
        / 2.0
        * (1.0 + horizon_brightening * math.sin(tilt_rad / 2.0) ** 3)
    )

    ground = sky.ghi * albedo * (1.0 - math.cos(tilt_rad)) / 2.0

    return max(beam + diffuse + ground, 0.0)


def compass_point(azimuth: float) -> str:
    """Return a 16-point compass label for an azimuth, for human-readable output."""
    points = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    return points[int((azimuth % 360.0) / 22.5 + 0.5) % 16]
